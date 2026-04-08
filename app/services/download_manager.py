import queue
import threading
import time
import requests
import os
from loguru import logger

class VideoDownloadQueue:
    def __init__(self, max_concurrent=3):
        self.queue = queue.Queue()
        self.max_concurrent = max_concurrent
        self.active_downloads = 0
        self.lock = threading.Lock()
        self.running = True
        self.workers = []
        self.completed_tasks = []
        self.failed_tasks = []
    
    def start(self):
        """Start the download queue workers"""
        for i in range(self.max_concurrent):
            worker = threading.Thread(target=self._worker, daemon=True)
            worker.start()
            self.workers.append(worker)
        logger.info(f"Download queue started with {self.max_concurrent} workers")
    
    def add_task(self, video_url, save_path, callback=None):
        """Add a download task to the queue"""
        task = {
            'video_url': video_url,
            'save_path': save_path,
            'callback': callback
        }
        self.queue.put(task)
        logger.debug(f"Added download task: {video_url}")
    
    def _worker(self):
        """Worker thread to process download tasks"""
        while self.running:
            try:
                task = self.queue.get(timeout=1)
                with self.lock:
                    self.active_downloads += 1
                
                # Execute download
                try:
                    success = self._download_video(task['video_url'], task['save_path'])
                    if success:
                        self.completed_tasks.append(task['save_path'])
                        if task['callback']:
                            task['callback'](success=True, path=task['save_path'])
                    else:
                        self.failed_tasks.append(task['video_url'])
                        if task['callback']:
                            task['callback'](success=False, error="Download failed")
                except Exception as e:
                    logger.error(f"Download failed: {e}")
                    self.failed_tasks.append(task['video_url'])
                    if task['callback']:
                        task['callback'](success=False, error=str(e))
                finally:
                    with self.lock:
                        self.active_downloads -= 1
                    self.queue.task_done()
            except queue.Empty:
                continue
    
    def _download_video(self, url, save_path):
        """Download video from URL to save path"""
        try:
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            
            # Download with streaming to save memory
            logger.info(f"Downloading video: {url}")
            response = requests.get(url, stream=True, timeout=30)
            response.raise_for_status()
            
            # Write to file in chunks
            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            logger.info(f"Video downloaded successfully: {save_path}")
            return True
        except Exception as e:
            logger.error(f"Error downloading video: {e}")
            # Clean up partially downloaded file
            if os.path.exists(save_path):
                try:
                    os.remove(save_path)
                except:
                    pass
            return False
    
    def stop(self):
        """Stop all worker threads"""
        self.running = False
        for worker in self.workers:
            worker.join(timeout=5)
        logger.info("Download queue stopped")
    
    def get_status(self):
        """Get current queue status"""
        with self.lock:
            return {
                'queue_size': self.queue.qsize(),
                'active_downloads': self.active_downloads,
                'completed_tasks': len(self.completed_tasks),
                'failed_tasks': len(self.failed_tasks),
                'max_concurrent': self.max_concurrent
            }
    
    def set_max_concurrent(self, new_max):
        """Set new maximum concurrent downloads and output INFO log"""
        with self.lock:
            old_max = self.max_concurrent
            self.max_concurrent = new_max
            logger.info(f"Download concurrent limit adjusted: {old_max} -> {new_max}")


class RateLimiter:
    def __init__(self, max_requests=10, time_window=60):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = []
        self.lock = threading.Lock()
    
    def acquire(self):
        """Acquire a token for a request, waiting if necessary"""
        with self.lock:
            current_time = time.time()
            # Clean up expired request records
            self.requests = [t for t in self.requests if current_time - t < self.time_window]
            
            if len(self.requests) >= self.max_requests:
                # Wait until there's available quota
                sleep_time = self.time_window - (current_time - self.requests[0])
                if sleep_time > 0:
                    logger.debug(f"Rate limit reached, waiting for {sleep_time:.2f} seconds")
                    time.sleep(sleep_time)
                # Clean up again after waiting
                current_time = time.time()
                self.requests = [t for t in self.requests if current_time - t < self.time_window]
            
            # Record new request
            self.requests.append(time.time())
            logger.debug(f"Rate limit: {len(self.requests)}/{self.max_requests} in last {self.time_window}s")


# Global instances
download_queue = VideoDownloadQueue(max_concurrent=3)
rate_limiter = RateLimiter(max_requests=10, time_window=60)

def initialize_download_system():
    """Initialize the download system"""
    global download_queue
    if not download_queue.workers:
        download_queue.start()

def download_video(video_url, save_path, callback=None):
    """Add a video download task to the queue"""
    # Acquire rate limit token
    rate_limiter.acquire()
    # Add to download queue
    download_queue.add_task(video_url, save_path, callback)

def get_download_status():
    """Get current download queue status"""
    return download_queue.get_status()

def set_max_concurrent_downloads(new_max):
    """Set new maximum concurrent downloads"""
    download_queue.set_max_concurrent(new_max)
