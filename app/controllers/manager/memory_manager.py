from queue import Queue

from app.controllers.manager.base_manager import QueuedTask, TaskManager


class InMemoryTaskManager(TaskManager):
    def create_queue(self) -> Queue[QueuedTask]:
        return Queue[QueuedTask]()

    def enqueue(self, task: QueuedTask) -> None:
        self.queue.put(task)

    def dequeue(self) -> QueuedTask:
        return self.queue.get()

    def is_queue_empty(self) -> bool:
        return self.queue.empty()
