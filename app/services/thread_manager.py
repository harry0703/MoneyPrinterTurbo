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
    """Task status enumeration"""
    PENDING = "pending"      # Waiting
    RUNNING = "running"      # Running
    COMPLETED = "completed"  # Completed
    FAILED = "failed"        # Failed
    CANCELLED = "cancelled"  # Cancelled

class TaskInfo:
    """Task information class"""
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
        """Convert to dictionary format"""
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
        """Create TaskInfo instance from dictionary"""
        task_info = cls(data['task_id'], task_func, args, kwargs)
        task_info.status = data['status']
        task_info.start_time = datetime.fromisoformat(data['start_time']) if data['start_time'] else None
        task_info.end_time = datetime.fromisoformat(data['end_time']) if data['end_time'] else None
        task_info.task_dir = data.get('task_dir', '')
        task_info.cancelled = data.get('cancelled', False)
        return task_info

class ThreadManager:
    def __init__(self, max_concurrent_tasks: int = 1, max_history: int = 20, save_file: str = 'tasks.json'):
        """Initialize thread manager
        
        Args:
            max_concurrent_tasks: Maximum number of concurrent tasks, default is 1
            max_history: Maximum number of historical task records, default is 20
            save_file: Task information save file path, default is 'tasks.json'
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
        
        # Load historical task information
        self._load_tasks()
    
    def _save_tasks(self):
        """Save task information to file"""
        try:
            with self.lock:
                # Only save historical and completed tasks
                tasks_to_save = []
                for task_info in self.history:
                    tasks_to_save.append(task_info.to_dict())
                
                # Save to file
                with open(self.save_file, 'w', encoding='utf-8') as f:
                    json.dump(tasks_to_save, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"Failed to save tasks: {str(e)}")
    
    def _load_tasks(self):
        """Load task information from file"""
        try:
            if os.path.exists(self.save_file):
                with open(self.save_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for task_data in data:
                        # Create TaskInfo instance for historical tasks (without function and parameters)
                        task_info = TaskInfo.from_dict(task_data)
                        self.history.append(task_info)
                    
                # Limit the number of historical records
                if len(self.history) > self.max_history:
                    self.history = self.history[:self.max_history]
        except Exception as e:
            logging.error(f"Failed to load tasks: {str(e)}")

    def submit_task(self, task_id: str, task_func: Callable, *args, **kwargs) -> Tuple[str, str]:
        """Submit task to background thread
        
        Args:
            task_id: Task ID
            task_func: Task function
            *args: Task function arguments
            **kwargs: Task function keyword arguments
            
        Returns:
            Tuple of (Task ID, status message)
            Status message indicates whether task was started immediately or queued
        """
        task_info = TaskInfo(task_id, task_func, args, kwargs)
        
        with self.lock:
            self.task_infos[task_id] = task_info
            self.task_queue.put(task_id)
            was_started = len(self.threads) < self.max_concurrent_tasks
            
        # Try to execute task
        self._process_queue()
        
        with self.lock:
            current_status = self.task_infos.get(task_id, TaskInfo(task_id, task_func, args, kwargs)).status
            
        if current_status == TaskStatus.RUNNING:
            return task_id, "started"
        else:
            return task_id, "queued"

    def _process_queue(self):
        """Process task queue"""
        with self.lock:
            if len(self.threads) < self.max_concurrent_tasks and not self.task_queue.empty():
                task_id = self.task_queue.get()
                if task_id in self.task_infos and self.task_infos[task_id].status == TaskStatus.PENDING:
                    self._start_task(task_id)

    def _start_task(self, task_id: str):
        """Start task
        
        Args:
            task_id: Task ID
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
        """Execute task in background thread

        Args:
            task_id: Task ID
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
        """Update task history record
        
        Args:
            task_id: Task ID
        """
        task_info = self.task_infos.get(task_id)
        if task_info:
            # Remove existing task with the same ID (if any)
            self.history = [t for t in self.history if t.task_id != task_id]
            # Add to the beginning of history
            self.history.insert(0, task_info)
            # Limit the number of historical records
            if len(self.history) > self.max_history:
                self.history = self.history[:self.max_history]
            # Save task information to file
            self._save_tasks()

    def is_task_running(self, task_id: str) -> bool:
        """Check if task is running
        
        Args:
            task_id: Task ID
            
        Returns:
            Whether task is running
        """
        with self.lock:
            return task_id in self.threads
    
    def get_task_result(self, task_id: str) -> Optional[Any]:
        """Get task result
        
        Args:
            task_id: Task ID
            
        Returns:
            Task result, returns None if task is not completed or failed
        """
        with self.lock:
            task_info = self.task_infos.get(task_id)
            return task_info.result if task_info else None
    
    def get_task_error(self, task_id: str) -> Optional[Exception]:
        """Get task error
        
        Args:
            task_id: Task ID
            
        Returns:
            Task error, returns None if task did not fail
        """
        with self.lock:
            task_info = self.task_infos.get(task_id)
            return task_info.error if task_info else None
    
    def clear_task_data(self, task_id: str):
        """Clear task data
        
        Args:
            task_id: Task ID
        """
        with self.lock:
            if task_id in self.task_infos:
                del self.task_infos[task_id]
            # Remove from history
            self.history = [t for t in self.history if t.task_id != task_id]

    def get_task_status(self, task_id: str) -> Optional[str]:
        """Get task status
        
        Args:
            task_id: Task ID
            
        Returns:
            Task status, returns None if task does not exist
        """
        with self.lock:
            task_info = self.task_infos.get(task_id)
            return task_info.status if task_info else None

    def get_all_tasks(self) -> List[Dict]:
        """Get all task information
        
        Returns:
            Task information list
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
            # Sort by status: Running > Pending > Others
            tasks.sort(key=lambda x: (x['status'] != TaskStatus.RUNNING, x['status'] != TaskStatus.PENDING))
        return tasks

    def get_history_tasks(self) -> List[Dict]:
        """Get historical task information
        
        Returns:
            Historical task information list
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
        """Cancel task
        
        Args:
            task_id: Task ID
            
        Returns:
            Whether cancellation was successful
        """
        with self.lock:
            if task_id not in self.task_infos:
                return False
            
            task_info = self.task_infos[task_id]
            
            # If task is running, set cancellation flag
            if task_info.status == TaskStatus.RUNNING:
                task_info.cancelled = True
                return True
            
            # If task is in queue, remove from queue
            elif task_info.status == TaskStatus.PENDING:
                # Rebuild queue, removing specified task
                new_queue = queue.Queue()
                while not self.task_queue.empty():
                    tid = self.task_queue.get()
                    if tid != task_id:
                        new_queue.put(tid)
                self.task_queue = new_queue
                del self.task_infos[task_id]
                return True
            
            # Task is already completed or failed, delete directly
            else:
                del self.task_infos[task_id]
                # Remove from history
                self.history = [t for t in self.history if t.task_id != task_id]
                return True

    def shutdown(self):
        """Shutdown thread manager"""
        self.running = False


# Global thread manager instance
thread_manager = ThreadManager()
