import json
from uuid import uuid4
from unittest.mock import patch

import pytest

from app.models.schema import AudioRequest, SubtitleRequest, VideoParams
from app.services import creative_studio, task, task_artifacts


BRIEF = {
    "subject": "A small garden in a city apartment",
    "goal": "Help beginners start a garden",
    "audience": "First-time apartment gardeners",
    "source_notes": "Herbs need adequate light and drainage.",
    "metric": "three_second_hold_rate",
}


def _experiment():
    def generate_script(**kwargs):
        prompt = kwargs["video_script_prompt"]
        angle = next(name for name, _ in creative_studio.HOOKS if name in prompt)
        return (
            f"{angle} opening. Show the pot. Explain drainage. Invite viewers to try."
        )

    with patch.object(
        creative_studio.llm, "generate_script", side_effect=generate_script
    ) as llm:
        experiment = creative_studio.create_experiment(
            BRIEF, app_config={"llm_provider": "ollama", "ollama_model_name": "local-1"}
        )
    assert llm.call_count == 3
    assert {v["id"] for v in experiment["variants"]} == {
        "question",
        "surprise",
        "demonstration",
    }
    assert all(len(v["storyboard"]) == 3 for v in experiment["variants"])
    assert experiment["cost_usd"] is None
    return experiment


def test_three_distinct_variants_enter_existing_generation_manifest(tmp_path):
    experiment = _experiment()
    selected = creative_studio.selected_manifest(experiment, "question")
    params = VideoParams(
        video_subject=BRIEF["subject"],
        video_script=experiment["variants"][0]["script"],
        creative_experiment=selected,
    )
    task_id = str(uuid4())
    (tmp_path / task_id).mkdir()
    with patch.object(
        task_artifacts.utils,
        "task_dir",
        side_effect=lambda name="": str(tmp_path / name),
    ):
        task.save_script_data(task_id, params.video_script, ["garden"], params)
    saved = json.loads((tmp_path / task_id / "script.json").read_text(encoding="utf-8"))
    assert saved["script"] == params.video_script
    assert saved["creative_experiment"]["selected_variant_id"] == "question"
    assert len(saved["creative_experiment"]["variants"]) == 3
    assert saved["creative_experiment"]["cost_usd"] is None
    assert saved["params"]["video_source"] == "pexels"


def test_duplicate_provider_output_is_not_offered_as_experiment():
    with patch.object(
        creative_studio.llm, "generate_script", return_value="Same output"
    ):
        with pytest.raises(ValueError, match="duplicate"):
            creative_studio.create_experiment(BRIEF)


def test_overlong_provider_output_is_rejected_before_selection():
    with patch.object(creative_studio.llm, "generate_script", return_value="x" * 8001):
        with pytest.raises(ValueError, match="8000-character"):
            creative_studio.create_experiment(BRIEF)


def test_csv_import_is_bounded_and_validates_counts():
    task_id = str(uuid4())
    header = "task_id,impressions,views,three_second_views,completed_views\n"
    rows = creative_studio.parse_analytics_csv(
        (header + f"{task_id},1000,500,300,100\n").encode()
    )
    assert rows[0]["three_second_views"] == 300
    with pytest.raises(ValueError, match="Counts"):
        creative_studio.parse_analytics_csv(
            (header + f"{task_id},100,50,60,10\n").encode()
        )
    with pytest.raises(ValueError, match="Duplicate"):
        creative_studio.parse_analytics_csv(
            (header + f"{task_id},100,50,30,10\n" * 2).encode()
        )
    with pytest.raises(ValueError, match="columns"):
        creative_studio.parse_analytics_csv(
            (header.strip() + ",viewer_email\n").encode()
        )
    with pytest.raises(ValueError, match="whole-number"):
        creative_studio.parse_analytics_csv(
            (header + f"{task_id},100,=50+1,30,10\n").encode()
        )
    with pytest.raises(ValueError, match="1 MiB"):
        creative_studio.parse_analytics_csv(b"a" * (creative_studio.MAX_CSV_BYTES + 1))


def test_observed_comparison_and_safe_task_persistence(tmp_path):
    experiment = _experiment()
    rows = []
    manifests = {}
    with patch.object(
        creative_studio.utils,
        "task_dir",
        side_effect=lambda name="": str(tmp_path / name),
    ):
        for variant_id, hold in (("question", 70), ("surprise", 55)):
            task_id = str(uuid4())
            directory = tmp_path / task_id
            directory.mkdir()
            manifest = creative_studio.selected_manifest(experiment, variant_id)
            script = next(
                item["script"]
                for item in manifest["variants"]
                if item["id"] == variant_id
            )
            (directory / "script.json").write_text(
                json.dumps({"script": script, "creative_experiment": manifest}),
                encoding="utf-8",
            )
            rows.append(
                {
                    "task_id": task_id,
                    "impressions": 200,
                    "views": 100,
                    "three_second_views": hold,
                    "completed_views": hold // 2,
                }
            )
            manifests[task_id] = creative_studio.task_manifest(task_id)

        report = creative_studio.compare_outcomes(rows, manifests)
        assert report["prediction"] is None
        assert "question" in report["next_batch_suggestion"]
        assert report["observed"][0]["three_second_hold_rate"] == 0.7

        # task_artifacts has its own utils import but shares the same module.
        assert creative_studio.save_outcomes(rows) == 2
        for row in rows:
            saved = json.loads((tmp_path / row["task_id"] / "script.json").read_text())
            assert saved["script"]
            assert saved["observed_outcome"] == row

        assert creative_studio.task_manifest("../escape") is None
        symlink_id = str(uuid4())
        (tmp_path / symlink_id).symlink_to(tmp_path / rows[0]["task_id"])
        assert creative_studio.task_manifest(symlink_id) is None

        tampered_path = tmp_path / rows[0]["task_id"] / "script.json"
        tampered = json.loads(tampered_path.read_text())
        tampered["script"] = "Unrelated script"
        tampered_path.write_text(json.dumps(tampered))
        assert creative_studio.task_manifest(rows[0]["task_id"]) is None


def test_small_samples_do_not_produce_winner():
    experiment = _experiment()
    task_id = str(uuid4())
    rows = [
        {
            "task_id": task_id,
            "impressions": 10,
            "views": 5,
            "three_second_views": 5,
            "completed_views": 5,
        }
    ]
    manifests = {
        task_id: {"manifest": creative_studio.selected_manifest(experiment, "question")}
    }
    report = creative_studio.compare_outcomes(rows, manifests)
    assert "Collect" in report["next_batch_suggestion"]


@pytest.mark.parametrize("request_type", [AudioRequest, SubtitleRequest])
def test_short_form_requests_save_script_without_creative_metadata(tmp_path, request_type):
    task_id = str(uuid4())
    (tmp_path / task_id).mkdir()
    params = request_type(video_script="Hello world.")
    with patch.object(
        task_artifacts.utils, "task_dir", side_effect=lambda name="": str(tmp_path / name)
    ):
        task.save_script_data(task_id, params.video_script, [], params)
    saved = json.loads((tmp_path / task_id / "script.json").read_text(encoding="utf-8"))
    assert saved["script"] == "Hello world."
    assert "creative_experiment" not in saved
