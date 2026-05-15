import threading
import queue
import logging
import time
import json
import os
from datetime import datetime
from typing import Dict, Optional, Callable, Any, List, Tuple

thread_local = threading.local()

class TaskStatus:
    """任务状态枚举"""
    PENDING = "pending"      # 等待中
    RUNNING = "running"      # 正在运行
    COMPLETED = "completed"  # 完成
    FAILED = "failed"        # 失败
    CANCELLED = "cancelled"  # 已取消

class TaskInfo:
    """任务信息类"""
    def __init__(self, task_id: str, task_func: Callable, args: tuple, kwargs: dict):
        self.task_id = task_id
        self.task_func = task_func
        self.args = args
        self.kwargs = kwargs
        self.status = TaskStatus.PENDING
        self.start_time = None
        self.end_time = None
        self.result = None
        self.error = None
        self.task_dir = kwargs.get('task_dir', '')
        self.cancelled = False
    
    def to_dict(self) -> Dict:
        """转换为字典格式"""
        return {
            'task_id': self.task_id,
            'status': self.status,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'task_dir': self.task_dir,
            'cancelled': self.cancelled
        }
    
    @classmethod
    def from_dict(cls, data: Dict, task_func: Callable = None, args: tuple = (), kwargs: dict = {}):
        """从字典创建TaskInfo实例"""
        task_info = cls(data['task_id'], task_func, args, kwargs)
        task_info.status = data['status']
        task_info.start_time = datetime.fromisoformat(data['start_time']) if data['start_time'] else None
        task_info.end_time = datetime.fromisoformat(data['end_time']) if data['end_time'] else None
        task_info.task_dir = data.get('task_dir', '')
        task_info.cancelled = data.get('cancelled', False)
        return task_info

class ThreadManager:
    def __init__(self, max_concurrent_tasks: int = 1, max_history: int = 20, save_file: str = 'tasks.json'):
        """初始化线程管理器
        
        Args:
            max_concurrent_tasks: 最大并发任务数，默认为1
            max_history: 最大历史任务记录数，默认为20
            save_file: 任务信息保存文件路径，默认为'tasks.json'
        """
        self.max_concurrent_tasks = max_concurrent_tasks
        self.max_history = max_history
        self.save_file = save_file
        self.threads: Dict[str, threading.Thread] = {}
        self.task_queue = queue.Queue()
        self.lock = threading.Lock()
        self.task_infos: Dict[str, TaskInfo] = {}
        self.history: List[TaskInfo] = []
        self.running = True
        
        # 加载历史任务信息
        self._load_tasks()
    
    def _save_tasks(self):
        """保存任务信息到文件"""
        try:
            with self.lock:
                # 只保存历史任务和已完成的任务
                tasks_to_save = []
                for task_info in self.history:
                    tasks_to_save.append(task_info.to_dict())
                
                # 保存到文件
                with open(self.save_file, 'w', encoding='utf-8') as f:
                    json.dump(tasks_to_save, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"Failed to save tasks: {str(e)}")
    
    def _load_tasks(self):
        """从文件加载任务信息"""
        try:
            if os.path.exists(self.save_file):
                with open(self.save_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for task_data in data:
                        # 为历史任务创建TaskInfo实例（不含函数和参数）
                        task_info = TaskInfo.from_dict(task_data)
                        self.history.append(task_info)
                    
                # 限制历史记录数量
                if len(self.history) > self.max_history:
                    self.history = self.history[:self.max_history]
        except Exception as e:
            logging.error(f"Failed to load tasks: {str(e)}")

    def submit_task(self, task_id: str, task_func: Callable, *args, **kwargs) -> str:
        """提交任务到后台线程
        
        Args:
            task_id: 任务ID
            task_func: 任务函数
            *args: 任务函数参数
            **kwargs: 任务函数关键字参数
            
        Returns:
            任务ID
        """
        task_info = TaskInfo(task_id, task_func, args, kwargs)
        
        with self.lock:
            self.task_infos[task_id] = task_info
            self.task_queue.put(task_id)
            
        # 尝试执行任务
        self._process_queue()
        return task_id

    def _process_queue(self):
        """处理任务队列"""
        with self.lock:
            if len(self.threads) < self.max_concurrent_tasks and not self.task_queue.empty():
                task_id = self.task_queue.get()
                if task_id in self.task_infos and self.task_infos[task_id].status == TaskStatus.PENDING:
                    self._start_task(task_id)

    def _start_task(self, task_id: str):
        """启动任务
        
        Args:
            task_id: 任务ID
        """
        task_info = self.task_infos.get(task_id)
        if not task_info or task_info.status != TaskStatus.PENDING:
            return
        
        task_info.status = TaskStatus.RUNNING
        task_info.start_time = datetime.now()
        
        thread = threading.Thread(
            target=self._run_task,
            args=(task_id,)
        )
        thread.daemon = True
        self.threads[task_id] = thread
        thread.start()

    def _run_task(self, task_id: str):
        """在后台线程中执行任务

        Args:
            task_id: 任务ID
        """
        task_info = self.task_infos.get(task_id)
        if not task_info:
            return

        try:
            thread_local.task_id = task_id

            def check_cancelled():
                return task_info.cancelled

            result = task_info.task_func(*task_info.args, **task_info.kwargs, check_cancelled=check_cancelled)

            with self.lock:
                if not task_info.cancelled:
                    task_info.status = TaskStatus.COMPLETED
                    task_info.result = result
                else:
                    task_info.status = TaskStatus.CANCELLED
        except Exception as e:
            logging.error(f"Task {task_id} failed: {str(e)}")
            with self.lock:
                task_info.status = TaskStatus.FAILED
                task_info.error = e
        finally:
            if hasattr(thread_local, 'task_id'):
                del thread_local.task_id

            with self.lock:
                task_info.end_time = datetime.now()
                if task_id in self.threads:
                    del self.threads[task_id]

                self._update_history(task_id)

                self._process_queue()

    def _update_history(self, task_id: str):
        """更新任务历史记录
        
        Args:
            task_id: 任务ID
        """
        task_info = self.task_infos.get(task_id)
        if task_info:
            # 移除已存在的相同任务ID（如果有）
            self.history = [t for t in self.history if t.task_id != task_id]
            # 添加到历史记录开头
            self.history.insert(0, task_info)
            # 限制历史记录数量
            if len(self.history) > self.max_history:
                self.history = self.history[:self.max_history]
            # 保存任务信息到文件
            self._save_tasks()

    def is_task_running(self, task_id: str) -> bool:
        """检查任务是否正在运行
        
        Args:
            task_id: 任务ID
            
        Returns:
            是否正在运行
        """
        with self.lock:
            return task_id in self.threads
    
    def get_task_result(self, task_id: str) -> Optional[Any]:
        """获取任务结果
        
        Args:
            task_id: 任务ID
            
        Returns:
            任务结果，如果任务未完成或失败则返回None
        """
        with self.lock:
            task_info = self.task_infos.get(task_id)
            return task_info.result if task_info else None
    
    def get_task_error(self, task_id: str) -> Optional[Exception]:
        """获取任务错误
        
        Args:
            task_id: 任务ID
            
        Returns:
            任务错误，如果任务未失败则返回None
        """
        with self.lock:
            task_info = self.task_infos.get(task_id)
            return task_info.error if task_info else None
    
    def clear_task_data(self, task_id: str):
        """清理任务数据
        
        Args:
            task_id: 任务ID
        """
        with self.lock:
            if task_id in self.task_infos:
                del self.task_infos[task_id]
            # 从历史记录中移除
            self.history = [t for t in self.history if t.task_id != task_id]

    def get_task_status(self, task_id: str) -> Optional[str]:
        """获取任务状态
        
        Args:
            task_id: 任务ID
            
        Returns:
            任务状态，如果任务不存在则返回None
        """
        with self.lock:
            task_info = self.task_infos.get(task_id)
            return task_info.status if task_info else None

    def get_all_tasks(self) -> List[Dict]:
        """获取所有任务信息
        
        Returns:
            任务信息列表
        """
        tasks = []
        with self.lock:
            for task_info in self.task_infos.values():
                task_data = {
                    'task_id': task_info.task_id,
                    'status': task_info.status,
                    'start_time': task_info.start_time.isoformat() if task_info.start_time else None,
                    'end_time': task_info.end_time.isoformat() if task_info.end_time else None,
                    'task_dir': task_info.task_dir
                }
                tasks.append(task_data)
            # 按状态排序：运行中 > 等待中 > 其他
            tasks.sort(key=lambda x: (x['status'] != TaskStatus.RUNNING, x['status'] != TaskStatus.PENDING))
        return tasks

    def get_history_tasks(self) -> List[Dict]:
        """获取历史任务信息
        
        Returns:
            历史任务信息列表
        """
        tasks = []
        with self.lock:
            for task_info in self.history:
                task_data = {
                    'task_id': task_info.task_id,
                    'status': task_info.status,
                    'start_time': task_info.start_time.isoformat() if task_info.start_time else None,
                    'end_time': task_info.end_time.isoformat() if task_info.end_time else None,
                    'task_dir': task_info.task_dir
                }
                tasks.append(task_data)
        return tasks

    def cancel_task(self, task_id: str) -> bool:
        """取消任务
        
        Args:
            task_id: 任务ID
            
        Returns:
            是否取消成功
        """
        with self.lock:
            if task_id not in self.task_infos:
                return False
            
            task_info = self.task_infos[task_id]
            
            # 如果任务正在运行，设置取消标志
            if task_info.status == TaskStatus.RUNNING:
                task_info.cancelled = True
                return True
            
            # 如果任务在队列中，从队列中移除
            elif task_info.status == TaskStatus.PENDING:
                # 重建队列，移除指定任务
                new_queue = queue.Queue()
                while not self.task_queue.empty():
                    tid = self.task_queue.get()
                    if tid != task_id:
                        new_queue.put(tid)
                self.task_queue = new_queue
                del self.task_infos[task_id]
                return True
            
            # 任务已完成或失败，直接删除
            else:
                del self.task_infos[task_id]
                # 从历史记录中移除
                self.history = [t for t in self.history if t.task_id != task_id]
                return True

    def shutdown(self):
        """关闭线程管理器"""
        self.running = False


# 全局线程管理器实例
thread_manager = ThreadManager()
