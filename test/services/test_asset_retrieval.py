import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import config
from app.services import asset_retrieval, llm
from app.services.asset_library import Asset, AssetTag

LINES = [
    ((0.0, 1.0), "Бот принимает оплату сам."),
    ((1.0, 2.0), "Клиент видит подтверждение."),
    ((2.0, 3.0), "Деньги приходят на счёт."),
    ((3.0, 4.0), "Ты ничего не делаешь руками."),
]


def _asset(asset_id: int, *, distance=None, tags=(), rel_path="") -> Asset:
    return Asset(
        id=asset_id,
        sha256=f"{asset_id:064x}",
        rel_path=rel_path or f"a/{asset_id}.jpg",
        width=1080,
        height=1920,
        caption=f"asset {asset_id}",
        distance=distance,
        tags=[AssetTag(tag=name, weight=weight) for name, weight in tags],
    )


class _Embedding:
    def __init__(self, vector=None):
        self.vector = [0.0] * 768 if vector is None else vector
        self.model = "embed-test"


class RetrievalTestCase(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)
        self.tagged_fallback = patch.object(
            asset_retrieval.asset_library,
            "tagged_assets_without_embedding",
            return_value=[],
        )
        self.tagged_fallback.start()
        config.app["photo_library_enabled"] = True
        config.app["photo_library_weight_semantic"] = 0.7
        config.app["photo_library_weight_tags"] = 0.3
        config.app["photo_library_weight_recency"] = 0.2
        config.app["photo_library_score_accept"] = 0.62
        config.app["photo_library_score_reject"] = 0.45
        config.app["photo_library_recency_window"] = 20

    def tearDown(self):
        self.tagged_fallback.stop()
        config.app.clear()
        config.app.update(self.original_app_config)


class TestScoring(RetrievalTestCase):
    def test_score_is_the_weighted_sum_of_its_parts(self):
        asset = _asset(1, distance=0.2, tags=[("кот", 0.8), ("окно", 0.4)])
        with (
            patch.object(
                asset_retrieval.asset_embed, "embed_text", return_value=_Embedding()
            ),
            patch.object(
                asset_retrieval.asset_library, "search_assets", return_value=[asset]
            ),
            patch.object(
                asset_retrieval.asset_library, "usage_counts", return_value={}
            ),
        ):
            [top] = asset_retrieval.rank_candidates("кот на окне", prefer_tags=["кот"])

        self.assertAlmostEqual(top.cosine, 0.8, places=6)
        self.assertAlmostEqual(top.tag_score, 0.8, places=6)
        self.assertAlmostEqual(top.recency_penalty, 0.0, places=6)
        self.assertAlmostEqual(top.score, 0.7 * 0.8 + 0.3 * 0.8, places=6)

    def test_weights_come_from_config(self):
        config.app["photo_library_weight_semantic"] = 1.0
        config.app["photo_library_weight_tags"] = 0.0
        config.app["photo_library_weight_recency"] = 0.5
        asset = _asset(1, distance=0.25, tags=[("кот", 1.0)])
        with (
            patch.object(
                asset_retrieval.asset_embed, "embed_text", return_value=_Embedding()
            ),
            patch.object(
                asset_retrieval.asset_library, "search_assets", return_value=[asset]
            ),
            patch.object(
                asset_retrieval.asset_library, "usage_counts", return_value={1: 1}
            ),
        ):
            [top] = asset_retrieval.rank_candidates("кот", prefer_tags=["кот"])

        self.assertAlmostEqual(top.tag_score, 1.0, places=6)
        self.assertAlmostEqual(top.recency_penalty, 0.5, places=6)
        self.assertAlmostEqual(top.score, 1.0 * 0.75 - 0.5 * 0.5, places=6)

    def test_tag_score_is_zero_without_prefer_tags(self):
        asset = _asset(1, distance=0.1, tags=[("кот", 1.0)])
        with (
            patch.object(
                asset_retrieval.asset_embed, "embed_text", return_value=_Embedding()
            ),
            patch.object(
                asset_retrieval.asset_library, "search_assets", return_value=[asset]
            ),
            patch.object(
                asset_retrieval.asset_library, "usage_counts", return_value={}
            ),
        ):
            [top] = asset_retrieval.rank_candidates("кот")
        self.assertEqual(top.tag_score, 0.0)

    def test_recency_penalty_grows_with_uses_and_reorders(self):
        fresh = _asset(1, distance=0.30)
        stale = _asset(2, distance=0.28)
        with (
            patch.object(
                asset_retrieval.asset_embed, "embed_text", return_value=_Embedding()
            ),
            patch.object(
                asset_retrieval.asset_library,
                "search_assets",
                return_value=[stale, fresh],
            ),
            patch.object(
                asset_retrieval.asset_library, "usage_counts", return_value={2: 3}
            ),
        ):
            ranked = asset_retrieval.rank_candidates("кадр", limit=5)

        self.assertEqual([item.asset.id for item in ranked], [1, 2])
        self.assertAlmostEqual(ranked[1].recency_penalty, 0.75, places=6)
        self.assertEqual(ranked[0].recency_penalty, 0.0)

    def test_recency_window_zero_skips_the_lookup(self):
        config.app["photo_library_recency_window"] = 0
        with (
            patch.object(
                asset_retrieval.asset_embed, "embed_text", return_value=_Embedding()
            ),
            patch.object(
                asset_retrieval.asset_library,
                "search_assets",
                return_value=[_asset(1, distance=0.1)],
            ),
            patch.object(asset_retrieval.asset_library, "usage_counts") as counts,
        ):
            asset_retrieval.rank_candidates("кадр")
        counts.assert_not_called()

    def test_ties_break_on_asset_id(self):
        assets = [
            _asset(7, distance=0.4),
            _asset(3, distance=0.4),
            _asset(5, distance=0.4),
        ]
        with (
            patch.object(
                asset_retrieval.asset_embed, "embed_text", return_value=_Embedding()
            ),
            patch.object(
                asset_retrieval.asset_library, "search_assets", return_value=assets
            ),
            patch.object(
                asset_retrieval.asset_library, "usage_counts", return_value={}
            ),
        ):
            ranked = asset_retrieval.rank_candidates("кадр", limit=3)
        self.assertEqual([item.asset.id for item in ranked], [3, 5, 7])

    def test_missing_distance_does_not_break_ranking(self):
        with (
            patch.object(
                asset_retrieval.asset_embed, "embed_text", return_value=_Embedding()
            ),
            patch.object(
                asset_retrieval.asset_library,
                "search_assets",
                return_value=[_asset(1, distance=None)],
            ),
            patch.object(
                asset_retrieval.asset_library, "usage_counts", return_value={}
            ),
        ):
            [top] = asset_retrieval.rank_candidates("кадр")
        self.assertEqual(top.cosine, 0.0)

    def test_verdict_ladder_follows_config(self):
        self.assertEqual(
            asset_retrieval.score_verdict(0.62), asset_retrieval.VERDICT_ACCEPT
        )
        self.assertEqual(
            asset_retrieval.score_verdict(0.5), asset_retrieval.VERDICT_GRAY
        )
        self.assertEqual(
            asset_retrieval.score_verdict(0.45), asset_retrieval.VERDICT_GRAY
        )
        self.assertEqual(
            asset_retrieval.score_verdict(0.4499), asset_retrieval.VERDICT_REJECT
        )

        config.app["photo_library_score_accept"] = 0.9
        config.app["photo_library_score_reject"] = 0.8
        self.assertEqual(
            asset_retrieval.score_verdict(0.85), asset_retrieval.VERDICT_GRAY
        )
        self.assertEqual(
            asset_retrieval.score_verdict(0.5), asset_retrieval.VERDICT_REJECT
        )

    def test_tag_and_id_filters_reach_the_database(self):
        with (
            patch.object(
                asset_retrieval.asset_embed, "embed_text", return_value=_Embedding()
            ),
            patch.object(
                asset_retrieval.asset_library, "search_assets", return_value=[]
            ) as search,
            patch.object(
                asset_retrieval.asset_library, "usage_counts", return_value={}
            ),
        ):
            asset_retrieval.rank_candidates(
                "кадр",
                only_tags=["свои"],
                exclude_tags=["мем"],
                exclude_ids=[4],
            )
        kwargs = search.call_args.kwargs
        self.assertEqual(kwargs["any_tags"], ("свои",))
        self.assertEqual(kwargs["exclude_tags"], ("мем",))
        self.assertEqual(kwargs["exclude_ids"], (4,))

    def test_preferred_tag_adds_unembedded_candidates(self):
        vector = _asset(2, distance=0.2, tags=[("other", 1.0)])
        tagged = _asset(1, distance=None, tags=[("own", 1.0)])
        with (
            patch.object(
                asset_retrieval.asset_embed, "embed_text", return_value=_Embedding()
            ),
            patch.object(
                asset_retrieval.asset_library, "search_assets", return_value=[vector]
            ),
            patch.object(
                asset_retrieval.asset_library,
                "tagged_assets_without_embedding",
                return_value=[tagged],
            ) as fallback,
            patch.object(
                asset_retrieval.asset_library, "usage_counts", return_value={}
            ),
        ):
            ranked = asset_retrieval.rank_candidates("кадр", prefer_tags=["own"])

        self.assertEqual([item.asset.id for item in ranked], [2, 1])
        self.assertEqual(ranked[0].cosine, 0.8)
        self.assertEqual(ranked[1].cosine, 0.0)
        self.assertEqual(ranked[1].tag_score, 1.0)
        self.assertEqual(fallback.call_args.kwargs["any_tags"], ("own",))

    def test_only_tags_drive_fallback_and_keep_exclusions(self):
        with (
            patch.object(
                asset_retrieval.asset_embed, "embed_text", return_value=_Embedding()
            ),
            patch.object(
                asset_retrieval.asset_library, "search_assets", return_value=[]
            ),
            patch.object(
                asset_retrieval.asset_library,
                "tagged_assets_without_embedding",
                return_value=[_asset(3, tags=[("own", 1.0)])],
            ) as fallback,
            patch.object(
                asset_retrieval.asset_library, "usage_counts", return_value={}
            ),
        ):
            ranked = asset_retrieval.rank_candidates(
                "кадр",
                prefer_tags=["preferred"],
                only_tags=["own"],
                exclude_tags=["meme"],
                exclude_ids=[7],
            )

        self.assertEqual([item.asset.id for item in ranked], [3])
        self.assertEqual(fallback.call_args.kwargs["any_tags"], ("own",))
        self.assertEqual(fallback.call_args.kwargs["exclude_tags"], ("meme",))
        self.assertEqual(fallback.call_args.kwargs["exclude_ids"], (7,))

    def test_no_tags_do_not_admit_arbitrary_unembedded_assets(self):
        with (
            patch.object(
                asset_retrieval.asset_embed, "embed_text", return_value=_Embedding()
            ),
            patch.object(
                asset_retrieval.asset_library,
                "search_assets",
                return_value=[_asset(2, distance=0.2)],
            ),
            patch.object(
                asset_retrieval.asset_library, "tagged_assets_without_embedding"
            ) as fallback,
            patch.object(
                asset_retrieval.asset_library, "usage_counts", return_value={}
            ),
        ):
            ranked = asset_retrieval.rank_candidates("кадр")

        self.assertEqual([item.asset.id for item in ranked], [2])
        fallback.assert_not_called()

    def test_fallback_deduplicates_without_changing_vector_candidate(self):
        vector = _asset(2, distance=0.2, tags=[("own", 1.0)])
        duplicate = _asset(2, distance=None, tags=[("own", 1.0)])
        tagged = _asset(3, distance=None, tags=[("own", 0.5)])
        tagged_duplicate = _asset(3, distance=None, tags=[("own", 0.1)])
        with (
            patch.object(
                asset_retrieval.asset_embed, "embed_text", return_value=_Embedding()
            ),
            patch.object(
                asset_retrieval.asset_library, "search_assets", return_value=[vector]
            ),
            patch.object(
                asset_retrieval.asset_library,
                "tagged_assets_without_embedding",
                return_value=[duplicate, tagged, tagged_duplicate],
            ),
            patch.object(
                asset_retrieval.asset_library, "usage_counts", return_value={}
            ),
        ):
            ranked = asset_retrieval.rank_candidates("кадр", prefer_tags=["own"])

        self.assertEqual([item.asset.id for item in ranked], [2, 3])
        self.assertEqual(ranked[0].cosine, 0.8)

    def test_fallback_failure_keeps_vector_candidates(self):
        with (
            patch.object(
                asset_retrieval.asset_embed, "embed_text", return_value=_Embedding()
            ),
            patch.object(
                asset_retrieval.asset_library,
                "search_assets",
                return_value=[_asset(2, distance=0.2)],
            ),
            patch.object(
                asset_retrieval.asset_library,
                "tagged_assets_without_embedding",
                side_effect=RuntimeError("db down"),
            ),
            patch.object(
                asset_retrieval.asset_library, "usage_counts", return_value={}
            ),
        ):
            ranked = asset_retrieval.rank_candidates("кадр", prefer_tags=["own"])

        self.assertEqual([item.asset.id for item in ranked], [2])

    def test_no_embedding_yields_no_candidates(self):
        with (
            patch.object(asset_retrieval.asset_embed, "embed_text", return_value=None),
            patch.object(asset_retrieval.asset_library, "search_assets") as search,
            patch.object(
                asset_retrieval.asset_library, "usage_counts", return_value={}
            ),
        ):
            self.assertEqual(asset_retrieval.rank_candidates("кадр"), [])
        search.assert_not_called()

    def test_search_failure_degrades_to_empty(self):
        with (
            patch.object(
                asset_retrieval.asset_embed, "embed_text", return_value=_Embedding()
            ),
            patch.object(
                asset_retrieval.asset_library,
                "search_assets",
                side_effect=RuntimeError("db down"),
            ),
            patch.object(
                asset_retrieval.asset_library, "usage_counts", return_value={}
            ),
        ):
            self.assertEqual(asset_retrieval.rank_candidates("кадр"), [])

    def test_usage_lookup_failure_degrades_to_no_penalty(self):
        with (
            patch.object(
                asset_retrieval.asset_embed, "embed_text", return_value=_Embedding()
            ),
            patch.object(
                asset_retrieval.asset_library,
                "search_assets",
                return_value=[_asset(1, distance=0.1)],
            ),
            patch.object(
                asset_retrieval.asset_library,
                "usage_counts",
                side_effect=RuntimeError("db down"),
            ),
        ):
            [top] = asset_retrieval.rank_candidates("кадр")
        self.assertEqual(top.recency_penalty, 0.0)


def _briefs(*indexes):
    return [{"index": index, "brief": f"кадр {index}"} for index in indexes]


def _fingerprint(selection):
    return (
        [
            (
                item.index,
                item.asset.id,
                item.verdict,
                round(item.candidate.score, 9) if item.candidate else None,
                round(item.margin, 9) if item.margin is not None else None,
            )
            for item in selection.assignments
        ],
        [(item.index, item.brief, item.reason) for item in selection.unsatisfied],
    )


class TestSelectAssets(RetrievalTestCase):
    def _select(
        self,
        *,
        briefs,
        by_brief,
        usage=None,
        require=(),
        resolved=None,
        **kwargs,
    ):
        """Run select_assets against a fake library keyed by brief text."""

        def embed(text, model=None):
            # the fake vector carries its brief, so the fake search can answer
            # a different pool per line
            return _Embedding([text])

        def search(vector, **call):
            pool = by_brief.get(vector[0], [])
            any_tags = call.get("any_tags") or ()
            exclude_tags = call.get("exclude_tags") or ()
            if any_tags:
                pool = [a for a in pool if set(a.tag_names()) & set(any_tags)]
            if exclude_tags:
                pool = [a for a in pool if not set(a.tag_names()) & set(exclude_tags)]
            return pool

        with (
            patch.object(
                asset_retrieval.llm, "generate_photo_briefs", return_value=briefs
            ),
            patch.object(asset_retrieval.asset_embed, "embed_text", side_effect=embed),
            patch.object(
                asset_retrieval.asset_library, "search_assets", side_effect=search
            ),
            patch.object(
                asset_retrieval.asset_library, "usage_counts", return_value=usage or {}
            ),
            patch.object(
                asset_retrieval,
                "_resolve_require",
                side_effect=lambda token: list((resolved or {}).get(token, [])),
            ),
        ):
            return asset_retrieval.select_assets(
                "автоворонка", LINES, amount=4, require=require, **kwargs
            )

    def test_picks_the_best_asset_per_line(self):
        result = self._select(
            briefs=_briefs(0, 2),
            by_brief={
                "кадр 0": [_asset(1, distance=0.1), _asset(2, distance=0.5)],
                "кадр 2": [_asset(3, distance=0.2)],
            },
        )
        self.assertEqual([a.index for a in result.assignments], [0, 2])
        self.assertEqual([a.asset.id for a in result.assignments], [1, 3])
        self.assertEqual(result.unsatisfied, [])
        self.assertEqual(result.assignments[0].verdict, asset_retrieval.VERDICT_ACCEPT)
        self.assertAlmostEqual(
            result.assignments[0].margin, 0.7 * 0.9 - 0.7 * 0.5, places=6
        )
        self.assertIsNone(result.assignments[1].margin)

    def test_one_asset_is_used_once_while_alternatives_remain(self):
        best = _asset(1, distance=0.05)
        second = _asset(2, distance=0.2)
        result = self._select(
            briefs=_briefs(0, 1),
            by_brief={"кадр 0": [best, second], "кадр 1": [best, second]},
        )
        self.assertEqual([a.asset.id for a in result.assignments], [1, 2])

    def test_line_without_alternatives_is_unsatisfied_with_its_brief(self):
        only = _asset(1, distance=0.05)
        result = self._select(
            briefs=_briefs(0, 3),
            by_brief={"кадр 0": [only], "кадр 3": [only]},
        )
        self.assertEqual([a.asset.id for a in result.assignments], [1])
        self.assertEqual(len(result.unsatisfied), 1)
        self.assertEqual(result.unsatisfied[0].index, 3)
        self.assertEqual(result.unsatisfied[0].brief, "кадр 3")
        self.assertEqual(
            result.unsatisfied[0].reason, asset_retrieval.REASON_NO_CANDIDATES
        )

    def test_grey_zone_is_used_and_flagged(self):
        result = self._select(
            briefs=_briefs(0),
            by_brief={"кадр 0": [_asset(1, distance=0.25)]},
        )
        self.assertEqual(result.assignments[0].verdict, asset_retrieval.VERDICT_GRAY)
        self.assertEqual(result.unsatisfied, [])

    def test_below_reject_is_never_used(self):
        result = self._select(
            briefs=_briefs(0),
            by_brief={"кадр 0": [_asset(1, distance=0.5)]},
        )
        self.assertEqual(result.assignments, [])
        self.assertEqual(
            result.unsatisfied[0].reason, asset_retrieval.REASON_BELOW_REJECT
        )
        self.assertEqual(result.unsatisfied[0].brief, "кадр 0")

    def test_recency_penalty_can_push_a_candidate_below_reject(self):
        result = self._select(
            briefs=_briefs(0),
            by_brief={"кадр 0": [_asset(1, distance=0.32)]},
            usage={1: 5},
        )
        self.assertEqual(result.assignments, [])
        self.assertEqual(
            result.unsatisfied[0].reason, asset_retrieval.REASON_BELOW_REJECT
        )

    def test_empty_pool_leaves_the_line_unsatisfied(self):
        result = self._select(briefs=_briefs(0, 1), by_brief={})
        self.assertEqual(result.assignments, [])
        self.assertEqual([u.index for u in result.unsatisfied], [0, 1])
        self.assertEqual([u.brief for u in result.unsatisfied], ["кадр 0", "кадр 1"])

    def test_only_tags_restrict_the_set(self):
        result = self._select(
            briefs=_briefs(0),
            by_brief={
                "кадр 0": [
                    _asset(1, distance=0.05, tags=[("сток", 1.0)]),
                    _asset(2, distance=0.2, tags=[("свои", 1.0)]),
                ]
            },
            only_tags=["свои"],
        )
        self.assertEqual([a.asset.id for a in result.assignments], [2])

    def test_exclude_tags_blacklist_assets(self):
        result = self._select(
            briefs=_briefs(0),
            by_brief={
                "кадр 0": [
                    _asset(1, distance=0.05, tags=[("мем", 1.0)]),
                    _asset(2, distance=0.2, tags=[("свои", 1.0)]),
                ]
            },
            exclude_tags=["мем"],
        )
        self.assertEqual([a.asset.id for a in result.assignments], [2])

    # ---------------- required assets ----------------

    def test_required_keep_their_order_and_ignore_thresholds(self):
        first = _asset(10, rel_path="own/start.jpg")
        second = _asset(11, rel_path="own/paid.jpg")
        result = self._select(
            briefs=_briefs(0, 1, 2),
            # required assets score terribly everywhere; order must still hold
            by_brief={
                "кадр 0": [_asset(10, distance=0.99), _asset(11, distance=0.05)],
                "кадр 1": [_asset(10, distance=0.99), _asset(11, distance=0.05)],
                "кадр 2": [_asset(10, distance=0.99), _asset(11, distance=0.05)],
            },
            require=("path:own/start.jpg", "path:own/paid.jpg"),
            resolved={
                "path:own/start.jpg": [first],
                "path:own/paid.jpg": [second],
            },
        )
        placed = [
            (a.index, a.asset.id)
            for a in result.assignments
            if a.verdict == asset_retrieval.VERDICT_REQUIRED
        ]
        self.assertEqual(placed, [(0, 10), (1, 11)])
        # the third line has nothing left of its own, but nothing was dropped
        self.assertEqual(
            [(u.index, u.reason) for u in result.unsatisfied],
            [(2, asset_retrieval.REASON_NO_CANDIDATES)],
        )

    def test_required_land_on_their_best_matching_line(self):
        wanted = _asset(10, rel_path="own/paid.jpg")
        result = self._select(
            briefs=_briefs(0, 1, 2),
            by_brief={
                "кадр 0": [_asset(10, distance=0.9)],
                "кадр 1": [_asset(10, distance=0.1)],
                "кадр 2": [_asset(10, distance=0.5)],
            },
            require=("path:own/paid.jpg",),
            resolved={"path:own/paid.jpg": [wanted]},
        )
        required = [a for a in result.assignments if a.verdict == "required"]
        self.assertEqual([(a.index, a.asset.id) for a in required], [(1, 10)])

    def test_required_order_wins_over_a_better_earlier_match(self):
        first = _asset(10, rel_path="own/a.jpg")
        second = _asset(11, rel_path="own/b.jpg")
        result = self._select(
            briefs=_briefs(0, 1, 2, 3),
            by_brief={
                "кадр 0": [_asset(10, distance=0.9), _asset(11, distance=0.01)],
                "кадр 1": [_asset(10, distance=0.01), _asset(11, distance=0.9)],
                "кадр 2": [_asset(10, distance=0.9), _asset(11, distance=0.1)],
                "кадр 3": [_asset(10, distance=0.9), _asset(11, distance=0.5)],
            },
            require=("path:own/a.jpg", "path:own/b.jpg"),
            resolved={"path:own/a.jpg": [first], "path:own/b.jpg": [second]},
        )
        required = [
            (a.index, a.asset.id)
            for a in result.assignments
            if a.verdict == asset_retrieval.VERDICT_REQUIRED
        ]
        # asset 11 fits line 0 best, but it was requested second, so it may only
        # land after asset 10
        self.assertEqual(required, [(1, 10), (2, 11)])

    def test_required_without_vector_information_fall_back_to_order(self):
        first = _asset(10, rel_path="own/a.jpg")
        second = _asset(11, rel_path="own/b.jpg")
        result = self._select(
            briefs=_briefs(1, 3),
            by_brief={},
            require=("path:own/a.jpg", "path:own/b.jpg"),
            resolved={"path:own/a.jpg": [first], "path:own/b.jpg": [second]},
        )
        self.assertEqual(
            [(a.index, a.asset.id) for a in result.assignments], [(1, 10), (3, 11)]
        )

    def test_required_that_does_not_fit_is_logged_and_reported(self):
        first = _asset(10, rel_path="own/a.jpg")
        second = _asset(11, rel_path="own/b.jpg")
        with patch.object(asset_retrieval.logger, "warning") as warning:
            result = self._select(
                briefs=_briefs(0),
                by_brief={"кадр 0": [first, second]},
                require=("path:own/a.jpg", "path:own/b.jpg"),
                resolved={"path:own/a.jpg": [first], "path:own/b.jpg": [second]},
            )
        logged = [str(call.args[0]) for call in warning.call_args_list]
        self.assertEqual([(a.index, a.asset.id) for a in result.assignments], [(0, 10)])
        self.assertEqual(len(result.unsatisfied), 1)
        self.assertEqual(
            result.unsatisfied[0].reason, asset_retrieval.REASON_REQUIRED_MISSING
        )
        self.assertEqual(result.unsatisfied[0].require, "path:own/b.jpg")
        self.assertIsNone(result.unsatisfied[0].index)
        self.assertTrue(any("own/b.jpg" in line for line in logged))

    def test_unresolvable_requirement_is_reported(self):
        result = self._select(
            briefs=_briefs(0),
            by_brief={"кадр 0": [_asset(1, distance=0.1)]},
            require=("tag:нет-такого",),
            resolved={},
        )
        self.assertEqual([u.require for u in result.unsatisfied], ["tag:нет-такого"])
        self.assertEqual([a.asset.id for a in result.assignments], [1])

    def test_required_asset_is_not_reused_by_the_scored_pass(self):
        wanted = _asset(10, rel_path="own/a.jpg")
        result = self._select(
            briefs=_briefs(0, 1),
            by_brief={
                "кадр 0": [_asset(10, distance=0.05)],
                "кадр 1": [_asset(10, distance=0.05), _asset(2, distance=0.2)],
            },
            require=("path:own/a.jpg",),
            resolved={"path:own/a.jpg": [wanted]},
        )
        self.assertEqual([a.asset.id for a in result.assignments], [10, 2])

    # ---------------- reproducibility and degradation ----------------

    def test_two_identical_runs_agree(self):
        kwargs = dict(
            briefs=_briefs(0, 1, 2),
            by_brief={
                "кадр 0": [_asset(1, distance=0.2), _asset(2, distance=0.2)],
                "кадр 1": [_asset(2, distance=0.2), _asset(1, distance=0.2)],
                "кадр 2": [_asset(3, distance=0.2), _asset(4, distance=0.2)],
            },
            prefer_tags=["свои"],
        )
        first = self._select(**kwargs)
        second = self._select(**kwargs)
        self.assertEqual(_fingerprint(first), _fingerprint(second))
        self.assertEqual(len(first.assignments), 3)

    def test_disabled_library_selects_nothing(self):
        config.app["photo_library_enabled"] = False
        with patch.object(asset_retrieval.llm, "generate_photo_briefs") as briefs:
            result = asset_retrieval.select_assets("тема", LINES)
        briefs.assert_not_called()
        self.assertEqual(result.assignments, [])
        self.assertEqual(result.unsatisfied, [])

    def test_no_briefs_selects_nothing(self):
        result = self._select(briefs=[], by_brief={})
        self.assertEqual(result.assignments, [])
        self.assertEqual(result.unsatisfied, [])

    def test_empty_script_selects_nothing(self):
        with patch.object(asset_retrieval.llm, "generate_photo_briefs") as briefs:
            result = asset_retrieval.select_assets("тема", [])
        briefs.assert_not_called()
        self.assertEqual(result.assignments, [])

    def test_embedding_outage_leaves_every_line_unsatisfied(self):
        with (
            patch.object(
                asset_retrieval.llm, "generate_photo_briefs", return_value=_briefs(0, 2)
            ),
            patch.object(asset_retrieval.asset_embed, "embed_text", return_value=None),
            patch.object(
                asset_retrieval.asset_library, "usage_counts", return_value={}
            ),
        ):
            result = asset_retrieval.select_assets("тема", LINES)
        self.assertEqual(result.assignments, [])
        self.assertEqual([u.brief for u in result.unsatisfied], ["кадр 0", "кадр 2"])

    def test_unexpected_failure_does_not_escape(self):
        with patch.object(
            asset_retrieval.llm,
            "generate_photo_briefs",
            side_effect=RuntimeError("llm exploded"),
        ):
            result = asset_retrieval.select_assets("тема", LINES)
        self.assertEqual(result.assignments, [])
        self.assertEqual(result.unsatisfied, [])


class TestRequireResolution(RetrievalTestCase):
    def test_path_requirement_matches_a_normalized_relative_path(self):
        wanted = _asset(5, rel_path="own/paid.jpg")
        with patch.object(
            asset_retrieval.asset_library,
            "list_assets",
            return_value=[_asset(4), wanted],
        ):
            self.assertEqual(
                asset_retrieval._resolve_require("path:./own\\paid.jpg"), [wanted]
            )

    def test_missing_path_resolves_to_nothing(self):
        with patch.object(
            asset_retrieval.asset_library, "list_assets", return_value=[]
        ):
            self.assertEqual(asset_retrieval._resolve_require("path:own/gone.jpg"), [])

    def test_tag_requirement_asks_the_library(self):
        with patch.object(
            asset_retrieval.asset_library, "list_assets", return_value=[_asset(6)]
        ) as listed:
            found = asset_retrieval._resolve_require("tag:бот")
        self.assertEqual([a.id for a in found], [6])
        self.assertEqual(listed.call_args.kwargs["any_tags"], ["бот"])

    def test_unknown_requirement_syntax_resolves_to_nothing(self):
        self.assertEqual(asset_retrieval._resolve_require("own/paid.jpg"), [])

    def test_blank_requirement_values_resolve_to_nothing(self):
        with patch.object(asset_retrieval.asset_library, "list_assets") as listed:
            self.assertEqual(asset_retrieval._resolve_require("path:  "), [])
            self.assertEqual(asset_retrieval._resolve_require("tag:  "), [])
        listed.assert_not_called()

    def test_path_lookup_walks_past_the_first_page(self):
        wanted = _asset(999, rel_path="own/paid.jpg")
        pages = [
            [_asset(i) for i in range(asset_retrieval._PATH_PAGE)],
            [wanted],
        ]
        with patch.object(
            asset_retrieval.asset_library, "list_assets", side_effect=pages
        ) as listed:
            self.assertEqual(
                asset_retrieval._resolve_require("path:own/paid.jpg"), [wanted]
            )
        self.assertEqual(
            [call.kwargs["offset"] for call in listed.call_args_list],
            [0, asset_retrieval._PATH_PAGE],
        )

    def test_unreadable_config_values_fall_back_to_defaults(self):
        config.app["photo_library_weight_semantic"] = "не число"
        config.app["photo_library_recency_window"] = "много"
        self.assertEqual(
            asset_retrieval._conf_float(
                "photo_library_weight_semantic", asset_retrieval.DEFAULT_WEIGHT_SEMANTIC
            ),
            asset_retrieval.DEFAULT_WEIGHT_SEMANTIC,
        )
        self.assertEqual(
            asset_retrieval._conf_int(
                "photo_library_recency_window", asset_retrieval.DEFAULT_RECENCY_WINDOW
            ),
            asset_retrieval.DEFAULT_RECENCY_WINDOW,
        )


class TestGeneratePhotoBriefs(unittest.TestCase):
    def test_parses_a_clean_response(self):
        response = json.dumps(
            [
                {"index": 2, "brief": "экран телефона с уведомлением о платеже"},
                {"index": 0, "brief": "ноутбук на кухонном столе"},
            ]
        )
        with patch(
            "app.services.llm._generate_response", return_value=response
        ) as call:
            briefs = llm.generate_photo_briefs("автоворонка", LINES, 5)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(
            briefs,
            [
                {"index": 0, "brief": "ноутбук на кухонном столе"},
                {"index": 2, "brief": "экран телефона с уведомлением о платеже"},
            ],
        )
        prompt = call.call_args.args[0]
        self.assertIn("автоворонка", prompt)
        self.assertIn("0. Бот принимает оплату сам.", prompt)

    def test_one_call_covers_every_line(self):
        response = json.dumps([{"index": 0, "brief": "кадр"}])
        with patch(
            "app.services.llm._generate_response", return_value=response
        ) as call:
            llm.generate_photo_briefs("тема", LINES, 4)
        self.assertEqual(call.call_count, 1)

    def test_recovers_a_json_array_from_chatty_output(self):
        response = (
            'Вот результат: [{"index": 1, "brief": "очередь у банкомата"}] готово'
        )
        with patch("app.services.llm._generate_response", return_value=response):
            briefs = llm.generate_photo_briefs("тема", LINES, 5)
        self.assertEqual(briefs, [{"index": 1, "brief": "очередь у банкомата"}])

    def test_drops_invalid_entries_and_caps_the_amount(self):
        response = json.dumps(
            [
                {"index": 0, "brief": "кадр ноль"},
                {"index": 0, "brief": "дубль"},
                {"index": 99, "brief": "вне сценария"},
                {"index": "две", "brief": "не число"},
                {"index": 1, "brief": "   "},
                {"index": 2, "brief": "кадр два"},
                {"index": 3, "brief": "кадр три"},
                "мусор",
            ]
        )
        with patch("app.services.llm._generate_response", return_value=response):
            briefs = llm.generate_photo_briefs("тема", LINES, 2)
        self.assertEqual(
            briefs,
            [{"index": 0, "brief": "кадр ноль"}, {"index": 2, "brief": "кадр два"}],
        )

    def test_garbage_response_returns_empty_after_retries(self):
        with patch(
            "app.services.llm._generate_response", return_value="не могу"
        ) as call:
            self.assertEqual(llm.generate_photo_briefs("тема", LINES, 5), [])
        self.assertEqual(call.call_count, llm._max_retries)

    def test_object_instead_of_array_returns_empty(self):
        with patch("app.services.llm._generate_response", return_value='{"index": 0}'):
            self.assertEqual(llm.generate_photo_briefs("тема", LINES, 5), [])

    def test_provider_error_returns_empty_without_retrying(self):
        with patch(
            "app.services.llm._generate_response", return_value="Error: no api key"
        ) as call:
            self.assertEqual(llm.generate_photo_briefs("тема", LINES, 5), [])
        self.assertEqual(call.call_count, 1)

    def test_empty_script_needs_no_call(self):
        with patch("app.services.llm._generate_response") as call:
            self.assertEqual(llm.generate_photo_briefs("тема", [], 5), [])
        call.assert_not_called()

    def test_blank_lines_need_no_call(self):
        with patch("app.services.llm._generate_response") as call:
            self.assertEqual(
                llm.generate_photo_briefs("тема", [((0.0, 1.0), "   ")], 5), []
            )
        call.assert_not_called()

    def test_app_config_is_forwarded(self):
        response = json.dumps([{"index": 0, "brief": "кадр"}])
        with patch(
            "app.services.llm._generate_response", return_value=response
        ) as call:
            llm.generate_photo_briefs("тема", LINES, 5, {"llm_provider": "gemini"})
        self.assertEqual(
            call.call_args.kwargs["app_config"], {"llm_provider": "gemini"}
        )


if __name__ == "__main__":
    unittest.main()
