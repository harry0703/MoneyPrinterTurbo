"""매일 소재 고르기."""

import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch

from app.services import daily
from app.services.sources.base import SourceItem


def _item(item_id, points=100):
    return SourceItem(
        source="hackernews",
        item_id=item_id,
        title=f"Show HN: thing {item_id}",
        url=f"https://example.com/{item_id}",
        points=points,
    )


class _Storage:
    """기록 파일을 임시 디렉터리로 돌린다."""

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._patch = patch.object(
            daily.utils, "storage_dir", return_value=self._tmp.name
        )
        self._patch.start()
        return self._tmp.name

    def __exit__(self, *args):
        self._patch.stop()
        self._tmp.cleanup()


class TestNotRepeatingYesterday(unittest.TestCase):
    def test_an_item_already_made_is_not_offered_again(self):
        """어제 만든 것을 오늘 또 만들면 채널이 같은 말을 반복한다."""
        items = [_item("1", 300), _item("2", 200), _item("3", 100)]
        with _Storage():
            with patch.object(daily.hackernews, "fetch_items", return_value=items):
                daily.mark_used(items[0])
                run = daily.pick_items(limit=3)

        self.assertEqual([p.item.item_id for p in run.picks], ["2", "3"])

    def test_showing_a_candidate_does_not_count_as_making_it(self):
        """
        보여 주기만 하고 넘어간 소재는 내일 다시 후보가 되어야 한다. 고르지 않은
        것까지 기록하면 좋은 소재가 하루 만에 사라진다.
        """
        items = [_item("1"), _item("2")]
        with _Storage():
            with patch.object(daily.hackernews, "fetch_items", return_value=items):
                daily.pick_items(limit=2)
                again = daily.pick_items(limit=2)

        self.assertEqual([p.item.item_id for p in again.picks], ["1", "2"])

    def test_an_old_record_stops_blocking_the_item(self):
        """
        반년 전에 한 번 나왔던 글이 다시 화제가 되면 그건 다시 다룰 만하다.
        """
        with _Storage() as work:
            stale = time.time() - (daily.SEEN_TTL_DAYS + 5) * 86400
            with open(os.path.join(work, daily.SEEN_FILE), "w", encoding="utf-8") as fp:
                json.dump({"hackernews:1": stale}, fp)

            with patch.object(
                daily.hackernews, "fetch_items", return_value=[_item("1")]
            ):
                run = daily.pick_items(limit=1)

        self.assertEqual([p.item.item_id for p in run.picks], ["1"])

    def test_no_matching_stories_still_counts_as_a_successful_look(self):
        """
        오늘 새 글이 없는 것과 소스에 못 닿은 것은 다르다. 같이 다루면 조용한
        날마다 폴링이 계속 다시 물어본다.
        """
        with _Storage():
            with patch.object(daily.hackernews, "fetch_items", return_value=[]):
                run = daily.pick_items()
        self.assertEqual(run.picks, ())
        self.assertTrue(run.source_reachable)

    def test_an_unreachable_source_says_so(self):
        with _Storage():
            with patch.object(daily.hackernews, "fetch_items", return_value=None):
                run = daily.pick_items()
        self.assertFalse(run.source_reachable)

    def test_the_last_run_date_survives_a_restart(self):
        """메모리에만 두면 봇을 다시 켤 때마다 그날 목록이 또 나간다."""
        with _Storage():
            self.assertEqual(daily.load_last_run(), "")
            self.assertTrue(daily.save_last_run("2026-08-03"))
            self.assertEqual(daily.load_last_run(), "2026-08-03")

    def test_a_failed_write_says_so(self):
        """
        조용히 실패하면 다음 실행이 기록이 없다고 판단해 같은 일을 다시 한다.
        """
        with _Storage():
            with patch.object(daily.json, "dump", side_effect=OSError("disk full")):
                self.assertFalse(daily.save_last_run("2026-08-03"))


class TestTheRecordSurvivesTrouble(unittest.TestCase):
    def test_a_broken_record_does_not_stop_today(self):
        """
        최악의 결과는 어제 것을 한 번 더 다루는 것이고, 그건 작업이 아예 안 도는
        것보다 낫다.
        """
        with _Storage() as work:
            with open(os.path.join(work, daily.SEEN_FILE), "w", encoding="utf-8") as fp:
                fp.write("{not json")
            self.assertEqual(daily.load_seen(), {})

    def test_a_record_that_is_not_an_object_is_discarded(self):
        with _Storage() as work:
            with open(os.path.join(work, daily.SEEN_FILE), "w", encoding="utf-8") as fp:
                json.dump(["not", "a", "map"], fp)
            self.assertEqual(daily.load_seen(), {})

    def test_the_record_does_not_grow_without_end(self):
        """하루 몇 건씩 몇 년이면 파일이 계속 자란다."""
        with _Storage():
            crowded = {f"hackernews:{i}": time.time() for i in range(daily.MAX_SEEN_ENTRIES + 500)}
            daily.save_seen(crowded)
            self.assertLessEqual(len(daily.load_seen()), daily.MAX_SEEN_ENTRIES)

    def test_the_newest_entries_are_the_ones_kept(self):
        """오래된 것부터 버려야 최근에 다룬 것을 다시 다루지 않는다."""
        with _Storage():
            now = time.time()
            crowded = {f"hackernews:{i}": now - i for i in range(daily.MAX_SEEN_ENTRIES + 10)}
            daily.save_seen(crowded)
            kept = daily.load_seen()

        self.assertIn("hackernews:0", kept)
        self.assertNotIn(f"hackernews:{daily.MAX_SEEN_ENTRIES + 9}", kept)

    def test_an_interrupted_write_does_not_destroy_the_record(self):
        """
        같은 파일에 바로 쓰면 도중에 멈췄을 때 반쯤 쓰인 파일이 남고, 다음 실행이
        기록을 통째로 잃는다.
        """
        with _Storage() as work:
            daily.save_seen({"hackernews:1": time.time()})
            with patch.object(daily.json, "dump", side_effect=OSError("disk full")):
                daily.save_seen({"hackernews:2": time.time()})

            self.assertEqual(list(daily.load_seen()), ["hackernews:1"])
            leftovers = [n for n in os.listdir(work) if n.startswith(".daily-seen-")]
            self.assertEqual(leftovers, [], "임시 파일이 남았다")


if __name__ == "__main__":
    unittest.main()
