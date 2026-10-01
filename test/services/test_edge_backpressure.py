import asyncio
import edge_tts
from unittest.mock import patch
import threading
import unittest
from app.services import voice


class TestEdgeProducerShutdown(unittest.TestCase):
    def test_callback_failure_stops_producer_and_closes_generator(self):
        resume = threading.Event()
        closed = threading.Event()
        consumed = []

        class Stream:
            def stream_sync(self):
                try:
                    yield {"type": "audio", "data": b"first"}
                    resume.wait(2)
                    for index in range(100):
                        consumed.append(index)
                        yield {"type": "audio", "data": b"tail"}
                finally:
                    closed.set()

        def fail(chunk):
            raise OSError("disk full")

        with self.assertRaisesRegex(OSError, "disk full"):
            voice._stream_edge_tts_sync_with_timeout(Stream(), fail, 2)
        resume.set()
        self.assertTrue(closed.wait(2), "producer did not finish")
        self.assertLessEqual(len(consumed), 2, "abandoned producer consumed the entire stream")

    def test_normal_stream_and_producer_error_are_forwarded(self):
        class Stream:
            def stream_sync(self):
                yield {"type": "audio", "data": b"first"}
                raise ValueError("broken stream")

        chunks = []
        with self.assertRaisesRegex(ValueError, "broken stream"):
            voice._stream_edge_tts_sync_with_timeout(Stream(), chunks.append, 2)
        self.assertEqual(chunks, [{"type": "audio", "data": b"first"}])

    def test_timed_out_stream_stops_when_blocked_read_returns(self):
        resume = threading.Event()
        closed = threading.Event()
        consumed = []
        class Stream:
            def stream_sync(self):
                try:
                    resume.wait(2)
                    for index in range(100):
                        consumed.append(index)
                        yield {"type": "audio", "data": b"late"}
                finally:
                    closed.set()
        try:
            with self.assertRaises(TimeoutError):
                voice._stream_edge_tts_sync_with_timeout(Stream(), lambda chunk: None, 0.01)
        finally:
            resume.set()
        self.assertTrue(closed.wait(2))
        self.assertLessEqual(len(consumed), 2)

    def test_real_sdk_stream_cancelled_without_draining_tail_after_callback_failure(self):
        resume = threading.Event()
        closed = threading.Event()
        fetched = []
        communicate = edge_tts.Communicate("Hello.", "en-US-AriaNeural")
        async def network_stream():
            try:
                yield {"type": "audio", "data": b"first"}
                while not resume.is_set():
                    await asyncio.sleep(0.001)
                for index in range(100):
                    fetched.append(index)
                    yield {"type": "audio", "data": b"tail"}
            finally:
                closed.set()
        def fail(chunk):
            raise OSError("disk full")
        with patch.object(communicate, "stream", new=network_stream):
            try:
                with self.assertRaisesRegex(OSError, "disk full"):
                    voice._stream_edge_tts_sync_with_timeout(communicate, fail, 2)
            finally:
                resume.set()
            self.assertTrue(closed.wait(2))
            self.assertLessEqual(len(fetched), 2)

    def test_real_sdk_blocked_async_read_is_cancelled_after_timeout(self):
        closed = threading.Event()
        started = threading.Event()
        communicate = edge_tts.Communicate("Hello.", "en-US-AriaNeural")
        async def network_stream():
            try:
                started.set()
                await asyncio.sleep(0.2)
                yield {"type": "audio", "data": b"late"}
            finally:
                closed.set()
        with patch.object(communicate, "stream", new=network_stream):
            with self.assertRaises(TimeoutError):
                voice._stream_edge_tts_sync_with_timeout(communicate, lambda chunk: None, 0.05)
            self.assertTrue(started.is_set())
            self.assertTrue(closed.wait(0.1), "SDK read was not cancelled promptly")
