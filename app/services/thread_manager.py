import threading
import queue
import logging
from typing import Dict, Optional, Callable, Any

class ThreadManager:
    def __init__(self):
        """初始化线程管理器"""
        self.threads: Dict[str, threading.Thread] = {}
        self.task_queue = queue.Queue()
        self.lock = threading.Lock()
        self.task_results: Dict[str, Any] = {}
        self.task_errors: Dict[str, Exception] = {}
        
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
        thread = threading.Thread(
            target=self._run_task,
            args=(task_id, task_func, args, kwargs)
        )
        thread.daemon = True
        
        with self.lock:
            self.threads[task_id] = thread
        
        thread.start()
        return task_id
    
    def _run_task(self, task_id: str, task_func: Callable, args: tuple, kwargs: dict):
        """在后台线程中执行任务
        
        Args:
            task_id: 任务ID
            task_func: 任务函数
            args: 任务函数参数
            kwargs: 任务函数关键字参数
        """
        try:
            result = task_func(*args, **kwargs)
            with self.lock:
                self.task_results[task_id] = result
        except Exception as e:
            # 记录错误信息
            logging.error(f"Task {task_id} failed: {str(e)}")
            with self.lock:
                self.task_errors[task_id] = e
        finally:
            # 任务完成后清理线程
            with self.lock:
                if task_id in self.threads:
                    del self.threads[task_id]
    
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
            return self.task_results.get(task_id)
    
    def get_task_error(self, task_id: str) -> Optional[Exception]:
        """获取任务错误
        
        Args:
            task_id: 任务ID
            
        Returns:
            任务错误，如果任务未失败则返回None
        """
        with self.lock:
            return self.task_errors.get(task_id)
    
    def clear_task_data(self, task_id: str):
        """清理任务数据
        
        Args:
            task_id: 任务ID
        """
        with self.lock:
            if task_id in self.task_results:
                del self.task_results[task_id]
            if task_id in self.task_errors:
                del self.task_errors[task_id]


# 全局线程管理器实例
thread_manager = ThreadManager()
