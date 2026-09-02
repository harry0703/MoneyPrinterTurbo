from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Callable

from app.services.trends.models import TrendSnapshot
from app.services.trends.scoring import cluster_signals, is_safe_topic, score_topic


DEFAULT_MARKETS = ("US", "IN", "GB", "CA", "AU")


class TrendDiscoveryService:
    def __init__(self, store, google_source, youtube_source, clock: Callable = None):
        self.store = store
        self.google_source = google_source
        self.youtube_source = youtube_source
        self.clock = clock or (lambda: datetime.now(UTC))

    def refresh(self) -> TrendSnapshot:
        collected_at = self.clock()
        google, google_status = self.google_source.fetch(DEFAULT_MARKETS, collected_at)
        youtube, youtube_status = self.youtube_source.fetch(DEFAULT_MARKETS, collected_at)
        statuses = {
            "google_trends": google_status,
            "youtube_most_popular": youtube_status,
        }
        if not google and not youtube:
            cached = self.store.load_latest()
            if cached is not None:
                return replace(cached, source_status=statuses, stale=True)
            return TrendSnapshot(collected_at, (), statuses, _empty_platforms(), True)

        previous = self.store.load_previous()
        youtube_topics = self._score(google + youtube, previous, verified=bool(youtube))
        inferred = self._score(google, previous, verified=False)
        platforms = {
            "youtube_shorts": youtube_topics,
            "tiktok": inferred,
            "instagram_reels": inferred,
        }
        topics = tuple(dict.fromkeys(topic.topic for topic in youtube_topics + inferred))
        by_name = {topic.topic: topic for topic in youtube_topics + inferred}
        snapshot = TrendSnapshot(
            collected_at=collected_at,
            topics=tuple(by_name[name] for name in topics),
            source_status=statuses,
            platforms=platforms,
        )
        self.store.save_snapshot(snapshot)
        return snapshot

    def get_cached(self):
        return self.store.load_latest()

    def shortlist(self, topic_id):
        topic = self._find(topic_id)
        if topic is not None:
            self.store.add_shortlist(topic)
        return topic

    def remove_shortlist(self, topic_id):
        return self.store.remove_shortlist(topic_id)

    def _score(self, signals, previous, verified):
        topics = []
        for candidate in cluster_signals(signals):
            if not is_safe_topic(candidate.topic):
                continue
            topic = score_topic(candidate, previous)
            topics.append(
                replace(
                    topic,
                    confidence_label="verified" if verified else "inferred",
                    angles=(),
                )
            )
        return tuple(
            sorted(
                topics,
                key=lambda item: (-item.retention_potential, item.topic.casefold()),
            )[:20]
        )

    def _find(self, topic_id):
        cached = self.get_cached()
        if cached is None:
            return None
        return next(
            (
                topic
                for topics in cached.platforms.values()
                for topic in topics
                if topic.topic.casefold() == topic_id.casefold()
            ),
            None,
        )


def _empty_platforms():
    return {"youtube_shorts": (), "tiktok": (), "instagram_reels": ()}
