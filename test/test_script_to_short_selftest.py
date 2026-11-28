import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = (
    Path(__file__).resolve().parent.parent
    / "contrib"
    / "script-to-short"
    / "skills"
    / "anime-talking-short"
    / "scripts"
)


@pytest.mark.parametrize(
    ("script", "args", "expected"),
    [
        ("render.py", ["--selftest"], "selftest ok"),
        ("sound.py", [], "sound selftest ok"),
    ],
)
def test_script_to_short_selftests(script, args, expected):
    # -I: do not import from the current directory or the script's neighbours.
    result = subprocess.run(
        [sys.executable, "-I", str(SCRIPTS / script), *args],
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert expected in result.stdout
