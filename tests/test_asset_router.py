from app.services import asset_router
from app.config import config


def test_route_assets_h3_flag():
    # create a minimal scene_plan preferring generated_video
    scene_plan = {"scenes": [{"scene_id": 1, "narration": "test", "asset_type": "generated_video"}]}
    # ensure h3_enabled is True for this test
    original = dict(config.app)
    try:
        config.app["h3_enabled"] = True
        decisions = asset_router.route_assets("test-task", params=None, scene_plan=scene_plan)
        assert isinstance(decisions, list)
        assert len(decisions) == 1
        assert decisions[0]["asset_type"] == "generated_video"
        # h3_requested should be present and truthy
        assert decisions[0].get("h3_requested") is True
    finally:
        # restore original config
        config.app.clear()
        config.app.update(original)
