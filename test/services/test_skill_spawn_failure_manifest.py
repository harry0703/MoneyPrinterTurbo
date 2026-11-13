import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest


spec = importlib.util.spec_from_file_location("mpt_agent_spawn_manifest", Path(__file__).resolve().parents[2] / "docs/skill/mpt_agent.py")
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


def test_actual_process_start_failure_records_terminal_manifest(tmp_path):
    missing_executable = str(tmp_path / "removed-uv")
    with patch.object(agent.shutil, "which", return_value=missing_executable), patch.object(agent, "run_checked"):
        with pytest.raises((OSError, agent.SkillError)):
            agent.generate_video(tmp_path, "fixture subject", [])
    payload = json.loads(agent.result_manifest_path(tmp_path).read_text())
    assert payload["status"] == "failed"
    assert payload["video_files"] == []
    assert payload["task_id"] and payload["log_file"]
    assert "start" in payload["error"]
