import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.state import RedisState


class _FakeRedis:
    def __init__(self, batches):
        self.batches = batches
        self.data = {}
        for key in [key for batch in batches for key in batch]:
            index = int(key.decode("utf-8").split(":")[-1])
            self.data[key] = {
                b"task_id": key,
                b"state": b"1",
                b"progress": str(index).encode("utf-8"),
            }

    def scan(self, cursor, count):
        batch_index = int(cursor)
        next_cursor = batch_index + 1
        if next_cursor >= len(self.batches):
            next_cursor = 0
        return next_cursor, self.batches[batch_index]

    def hgetall(self, key):
        return self.data[key]


class TestRedisState(unittest.TestCase):
    def _build_state(self, batch_sizes):
        keys = [f"task:{i}".encode("utf-8") for i in range(sum(batch_sizes))]
        batches = []
        offset = 0
        for batch_size in batch_sizes:
            batches.append(keys[offset : offset + batch_size])
            offset += batch_size

        state = RedisState.__new__(RedisState)
        state._redis = _FakeRedis(batches)
        return state

    def test_get_all_tasks_paginates_across_scan_batches(self):
        """
        Redis SCAN 이 key 를 배치로 나누어 반환할 때, 페이지 슬라이스는 현재 배치의 시작 위치를 기준으로 계산해야 합니다.

        이 케이스는 PR #890 에서 설명한 18개 작업, page_size=10 시나리오를 재현합니다:
        첫 번째 배치 10개, 두 번째 배치 8개. 기존 로직에서는 첫 페이지가 빈 목록을 반환하고 두 번째 페이지는
        2개만 반환했습니다. 수정 후에는 첫 페이지가 10개, 두 번째 페이지가 나머지 8개를 반환합니다.
        """
        state = self._build_state([10, 8])

        first_page, first_total = state.get_all_tasks(page=1, page_size=10)
        second_page, second_total = state.get_all_tasks(page=2, page_size=10)

        self.assertEqual(first_total, 18)
        self.assertEqual(second_total, 18)
        self.assertEqual(len(first_page), 10)
        self.assertEqual(len(second_page), 8)
        self.assertEqual(
            [task["task_id"] for task in first_page],
            [f"task:{i}" for i in range(10)],
        )
        self.assertEqual(
            [task["task_id"] for task in second_page],
            [f"task:{i}" for i in range(10, 18)],
        )


if __name__ == "__main__":
    unittest.main()
