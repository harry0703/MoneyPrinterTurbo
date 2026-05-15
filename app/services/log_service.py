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
        self._logs = deque(maxlen=3000)
        self._log_file = None
        self._setup_log_file()
        self._websocket_connections = set()
        self._connections_lock = threading.Lock()
        self._event_loop = None
        self._loop_lock = threading.Lock()

    def set_event_loop(self, loop):
        """Set the event loop for WebSocket broadcasting."""
        with self._loop_lock:
            self._event_loop = loop

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
        pass

        if self._log_file:
            with open(self._log_file, "a", encoding="utf-8") as f:
                timestamp = log_entry["timestamp"]
                task_info = f"[Task: {task_id}] " if task_id else ""
                f.write(f"{timestamp} | {level.upper()} | {task_info}{message}\n")

        # Push log to all connected WebSocket clients
        import asyncio
        try:
            with self._loop_lock:
                loop = self._event_loop
            
            if loop and loop.is_running():
                asyncio.run_coroutine_threadsafe(self._broadcast_log(log_entry), loop)
            else:
                try:
                    current_loop = asyncio.get_event_loop()
                    if current_loop.is_running():
                        asyncio.create_task(self._broadcast_log(log_entry))
                    else:
                        asyncio.run(self._broadcast_log(log_entry))
                except RuntimeError:
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    new_loop.run_until_complete(self._broadcast_log(log_entry))
                    new_loop.close()
        except Exception:
            pass

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
        self._logs = deque([log for log in self._logs if log.get("task_id") != task_id], maxlen=3000)

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

    async def _broadcast_log(self, log_entry):
        """Broadcast a log entry to all connected WebSocket clients."""
        import json
        import asyncio
        from fastapi import WebSocket

        with self._connections_lock:
            connections = list(self._websocket_connections)

        if not connections:
            return

        async def send_to_connection(connection):
            try:
                await connection.send_json(log_entry)
            except Exception:
                self.remove_websocket_connection(connection)

        # Send to all connections concurrently
        if connections:
            await asyncio.gather(*(send_to_connection(conn) for conn in connections))


class LoguruHandler:
    def __init__(self, log_service: LogService):
        self.log_service = log_service

    def __call__(self, message):
        try:
            record = message.record
            level = record["level"].name

            extra = record.get("extra", {})
            task_id = extra.get("task_id")
            
            if task_id is None:
                import threading
                thread_local = threading.local()
                task_id = getattr(thread_local, 'task_id', None)
            
            # print(f"[LoguruHandler] Received log: level={level}, message={record['message'][:50]}...")

            self.log_service.add_log(level, record["message"], task_id)
        except Exception as e:
            # print(f"[LoguruHandler] Error processing log: {e}")
            pass


log_service = LogService()
loguru_handler = LoguruHandler(log_service)
handler_id = logger.add(loguru_handler, format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}", level="INFO")
# print(f"[LogService] LoguruHandler registered with ID: {handler_id}")
# print(f"[LogService] Total handlers registered: {len(logger._core.handlers)}")
