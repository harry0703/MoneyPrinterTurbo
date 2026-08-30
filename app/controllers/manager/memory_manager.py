"""进程内任务队列：适用于单机、未启用 Redis 的部署。"""

from queue import Queue
from typing import Dict

from app.controllers.manager.base_manager import TaskManager


class InMemoryTaskManager(TaskManager):
    """用标准库 ``Queue`` 保存等待执行的任务。"""
    def create_queue(self):
        return Queue(maxsize=self.max_queued_tasks)

    def enqueue(self, task: Dict):
        self.queue.put(task)

    def dequeue(self):
        return self.queue.get()

    def is_queue_empty(self):
        return self.queue.empty()

    def queue_size(self):
        return self.queue.qsize()
