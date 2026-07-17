import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.models import const
from app.services.state import MemoryState, RedisState


class _IdempotencyContract(unittest.TestCase):
    # Prevent pytest from collecting the shared base as a runnable test class.
    __test__ = False

    """
    Shared behavioral contract for Memory and Redis state adapters.

    Validates the acceptance criteria observable at the state layer: first
    reservation, identical retry, payload conflict, queue-rejection cleanup,
    and concurrent identical reservations yielding exactly one ``created``.
    """

    def test_first_reservation_is_created(self):
        outcome = self.state.reserve_idempotent_task("k1", "h1")
        self.assertEqual(outcome, const.IDEMPOTENCY_CREATED)

    def test_identical_retry_is_duplicate(self):
        self.state.reserve_idempotent_task("k1", "h1")
        outcome = self.state.reserve_idempotent_task("k1", "h1")
        self.assertEqual(outcome, const.IDEMPOTENCY_DUPLICATE)

    def test_different_params_is_conflict(self):
        self.state.reserve_idempotent_task("k1", "h1")
        outcome = self.state.reserve_idempotent_task("k1", "h2")
        self.assertEqual(outcome, const.IDEMPOTENCY_CONFLICT)

    def test_clear_idempotency_allows_retry_after_rejection(self):
        self.state.reserve_idempotent_task("k1", "h1")
        self.state.clear_idempotency("k1")
        outcome = self.state.reserve_idempotent_task("k1", "h1")
        self.assertEqual(outcome, const.IDEMPOTENCY_CREATED)

    def test_concurrent_identical_reservations_create_one_task(self):
        thread_count = 20
        results = []

        def reserve():
            results.append(
                self.state.reserve_idempotent_task("same-key", "same-hash")
            )

        threads = [threading.Thread(target=reserve) for _ in range(thread_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(results.count(const.IDEMPOTENCY_CREATED), 1)
        self.assertEqual(
            results.count(const.IDEMPOTENCY_DUPLICATE), thread_count - 1
        )


class TestMemoryStateIdempotency(_IdempotencyContract):
    __test__ = True

    def setUp(self):
        self.state = MemoryState()


class _FakeRedisSet:
    """Minimal redis stand-in covering the idempotency operations used."""

    def __init__(self):
        # key -> (value, expires_at). expires_at is None for no expiry.
        self.data = {}

    def set(self, key, value, nx=False, get=False, ex=None):
        exists = key in self.data
        if nx and exists:
            return self.data[key][0] if get else None
        old = self.data[key][0] if exists else None
        self.data[key] = (value, None)
        return old if get else None

    def delete(self, key):
        self.data.pop(key, None)


class TestRedisStateIdempotency(_IdempotencyContract):
    __test__ = True

    def setUp(self):
        state = RedisState.__new__(RedisState)
        state._redis = _FakeRedisSet()
        self.state = state


if __name__ == "__main__":
    unittest.main()
