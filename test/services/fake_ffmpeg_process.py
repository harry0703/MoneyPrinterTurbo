import io


class FakeFfmpegProcess:
    """Stands in for the Popen object that streams FFmpeg's decode output."""

    def __init__(self, stdout=b"", stderr=b"", returncode=0):
        self.stdout = io.BytesIO(stdout) if isinstance(stdout, bytes) else stdout
        self.stderr = io.BytesIO(stderr)
        self.returncode = returncode

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False
