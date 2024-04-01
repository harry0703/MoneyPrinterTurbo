# State Management
# This module is responsible for managing the state of the application.
import math

# 如果你部署在分布式环境中，你可能需要一个中心化的状态管理服务，比如 Redis 或者数据库。
# 如果你的应用程序是单机的，你可以使用内存来存储状态。

# If you are deploying in a distributed environment, you might need a centralized state management service like Redis or a database.
# If your application is single-node, you can use memory to store the state.

from app.models import const
from app.utils import utils

_tasks = {}


def update_task(task_id: str, state: int = const.TASK_STATE_PROCESSING, progress: int = 0, **kwargs):
    """
    Set the state of the task.
    """
    progress = int(progress)
    if progress > 100:
        progress = 100

    _tasks[task_id] = {
        "state": state,
        "progress": progress,
        **kwargs,
    }

def get_task(task_id: str):
    """
    Get the state of the task.
    """
    return _tasks.get(task_id, None)
