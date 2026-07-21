from queue import Queue
from typing import Dict

from app.controllers.manager.base_manager import TaskManager


class InMemoryTaskManager(TaskManager):
    def create_queue(self):
        # Idempotent submissions are accepted into the queue before dispatch.
        # Active slots therefore need temporary queue capacity as well as the
        # configured waiting-task capacity.
        return Queue(maxsize=self.max_queued_tasks + self.max_concurrent_tasks)

    def enqueue(self, task: Dict):
        """Append a job to the bounded in-memory queue."""
        self.queue.put(task)

    def dequeue(self):
        """Remove and return the oldest in-memory job."""
        return self.queue.get()

    def is_queue_empty(self):
        return self.queue.empty()

    def queue_size(self):
        return self.queue.qsize()
