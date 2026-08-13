from app.services import asset_validator


def test_score_candidate_basic():
    scene = {"duration": 5.0, "aspect_ratio": 16/9}
    candidate = {"duration": 5.0, "width": 1280, "height": 720}
    score = asset_validator.score_candidate(scene, candidate)
    assert isinstance(score, dict)
    assert score["final_score"] > 0.0
    assert score["quality_score"] == 1.0
    # duration should be 1.0 when candidate duration >= requested
    assert score["duration_score"] == 1.0


def test_score_candidate_short_duration():
    scene = {"duration": 10.0}
    candidate = {"duration": 5.0, "width": 640, "height": 360}
    score = asset_validator.score_candidate(scene, candidate)
    assert score["duration_score"] == 0.5
    assert 0.0 <= score["final_score"] <= 1.0
