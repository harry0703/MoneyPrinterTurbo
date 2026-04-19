import os
import threading
from datetime import datetime
from collections import deque
from loguru import logger


class LogService:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._logs = deque(maxlen=1000)
        self._log_file = None
        self._setup_log_file()
        self._websocket_connections = set()
        self._connections_lock = threading.Lock()

    def _setup_log_file(self):
        log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))), "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file_name = datetime.now().strftime("%Y%m%d_%H%M%S") + ".log"
        self._log_file = os.path.join(log_dir, log_file_name)

    def add_log(self, level: str, message: str, task_id: str = None):
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "level": level.upper(),
            "message": message,
            "task_id": task_id
        }
        self._logs.append(log_entry)

        if self._log_file:
            with open(self._log_file, "a", encoding="utf-8") as f:
                timestamp = log_entry["timestamp"]
                task_info = f"[Task: {task_id}] " if task_id else ""
                f.write(f"{timestamp} | {level.upper()} | {task_info}{message}\n")

        # Push log to all connected WebSocket clients
        self._broadcast_log(log_entry)

    def get_logs(self, level: str = None, task_id: str = None, limit: int = 100, offset: int = 0):
        filtered_logs = list(self._logs)

        if level:
            filtered_logs = [log for log in filtered_logs if log["level"] == level.upper()]

        if task_id:
            filtered_logs = [log for log in filtered_logs if log.get("task_id") == task_id]

        total = len(filtered_logs)
        # Get the latest logs by reversing the list
        filtered_logs.reverse()
        paginated_logs = filtered_logs[offset:offset + limit]

        return {
            "logs": paginated_logs,
            "total": total,
            "limit": limit,
            "offset": offset
        }

    def clear_logs(self):
        self._logs.clear()

    def clear_task_logs(self, task_id: str):
        """删除特定任务的日志
        
        Args:
            task_id: 任务ID
        """
        # 从内存中删除特定任务的日志
        self._logs = deque([log for log in self._logs if log.get("task_id") != task_id], maxlen=1000)

    def get_log_file_path(self):
        return self._log_file

    def add_websocket_connection(self, connection):
        """Add a WebSocket connection to the set of active connections."""
        with self._connections_lock:
            self._websocket_connections.add(connection)

    def remove_websocket_connection(self, connection):
        """Remove a WebSocket connection from the set of active connections."""
        with self._connections_lock:
            if connection in self._websocket_connections:
                self._websocket_connections.remove(connection)

    def _broadcast_log(self, log_entry):
        """Broadcast a log entry to all connected WebSocket clients."""
        import json
        from fastapi import WebSocket

        with self._connections_lock:
            connections = list(self._websocket_connections)

        for connection in connections:
            try:
                # Send log entry as JSON
                connection.send_json(log_entry)
            except Exception as e:
                # If sending fails, remove the connection
                logger.error(f"Error sending log to WebSocket: {e}")
                self.remove_websocket_connection(connection)


class LoguruHandler:
    def __init__(self, log_service: LogService):
        self.log_service = log_service

    def __call__(self, message):
        record = message.record
        level = record["level"].name

        extra = record.get("extra", {})
        task_id = extra.get("task_id")

        self.log_service.add_log(level, record["message"], task_id)


log_service = LogService()
loguru_handler = LoguruHandler(log_service)
logger.add(loguru_handler, format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}", level="INFO")
