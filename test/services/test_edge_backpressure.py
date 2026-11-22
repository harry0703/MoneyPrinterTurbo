import asyncio
import edge_tts
from unittest.mock import patch
import threading
import time
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

    def test_real_sdk_ready_chunks_are_not_throttled_into_a_timeout(self):
        # Long narrations stream thousands of chunks; each one must be handed
        # over as soon as the previous one is taken, not after a fixed sleep.
        communicate = edge_tts.Communicate("Hello.", "en-US-AriaNeural")
        expected = [index.to_bytes(2, "big") for index in range(500)]
        async def network_stream():
            for data in expected:
                yield {"type": "audio", "data": data}
        chunks = []
        with patch.object(communicate, "stream", new=network_stream):
            voice._stream_edge_tts_sync_with_timeout(communicate, chunks.append, 2)
        self.assertEqual([chunk["data"] for chunk in chunks], expected)

    def test_stream_longer_than_timeout_finishes_while_chunks_keep_arriving(self):
        # An 8000-character script legitimately needs more than the idle
        # timeout in total; only a gap without data should abort it.
        class Stream:
            def stream_sync(self):
                for index in range(5):
                    time.sleep(0.15)
                    yield {"type": "audio", "data": str(index).encode()}

        chunks = []
        voice._stream_edge_tts_sync_with_timeout(Stream(), chunks.append, 0.5)
        self.assertEqual([chunk["data"] for chunk in chunks], [b"0", b"1", b"2", b"3", b"4"])

    def test_stream_that_stalls_after_progress_still_times_out(self):
        resume = threading.Event()

        class Stream:
            def stream_sync(self):
                yield {"type": "audio", "data": b"first"}
                resume.wait(2)
                yield {"type": "audio", "data": b"late"}

        chunks = []
        try:
            with self.assertRaises(TimeoutError):
                voice._stream_edge_tts_sync_with_timeout(Stream(), chunks.append, 0.1)
        finally:
            resume.set()
        self.assertEqual(chunks, [{"type": "audio", "data": b"first"}])

    def test_async_adapter_restarts_idle_timeout_after_each_chunk(self):
        class Communicate:
            def stream(self):
                async def events():
                    for index in range(12):
                        await asyncio.sleep(0.05)
                        yield {"type": "audio", "data": bytes([index])}

                return events()

        chunks = []
        voice.stream_edge_tts_chunks(Communicate(), chunks.append, 0.3)
        self.assertEqual([chunk["data"] for chunk in chunks], [bytes([i]) for i in range(12)])

    def test_timing_events_without_audio_still_hit_the_overall_limit(self):
        # Boundary events reset the idle timer. They must not postpone the
        # separate overall limit, or a stream with no audio holds a worker.
        class Stream:
            def stream_sync(self):
                while True:
                    time.sleep(0.02)
                    yield {"type": "WordBoundary", "offset": 0, "duration": 100000}

        chunks = []
        started = time.monotonic()
        with self.assertRaises(TimeoutError) as caught:
            voice._stream_edge_tts_sync_with_timeout(
                Stream(), chunks.append, 5, total_timeout_seconds=0.25
            )
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertIn("overall", str(caught.exception))
        self.assertTrue(chunks)
        self.assertTrue(all(chunk["type"] == "WordBoundary" for chunk in chunks))

    def test_audio_longer_than_idle_timeout_finishes_inside_the_overall_limit(self):
        class Stream:
            def stream_sync(self):
                for index in range(6):
                    time.sleep(0.08)
                    yield {"type": "audio", "data": bytes([index])}

        chunks = []
        voice._stream_edge_tts_sync_with_timeout(
            Stream(), chunks.append, 0.2, total_timeout_seconds=1
        )
        self.assertEqual([chunk["data"] for chunk in chunks], [bytes([i]) for i in range(6)])

    def test_async_timing_events_without_audio_hit_the_overall_limit(self):
        class Communicate:
            def stream(self):
                async def events():
                    while True:
                        await asyncio.sleep(0.02)
                        yield {"type": "WordBoundary", "offset": 0, "duration": 100000}

                return events()

        chunks = []
        started = time.monotonic()
        with self.assertRaises(TimeoutError) as caught:
            voice.stream_edge_tts_chunks(
                Communicate(), chunks.append, 5, total_timeout_seconds=0.25
            )
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertIn("overall", str(caught.exception))
        self.assertTrue(chunks)
