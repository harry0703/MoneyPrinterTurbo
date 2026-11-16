import io
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from loguru import logger

from app.utils import logging_utils

ROOT = Path(__file__).resolve().parents[2]
# None of the Windows ANSI code pages can encode all of these: the circled
# digits generate_video() logs, Chinese, an emoji and the narrow no-break
# space French puts before "!". cp936 (Chinese Windows) only lacks the last two.
MESSAGE = "① 你好 🤖 C’est\N{NARROW NO-BREAK SPACE}!"


def _legacy_stream():
    return io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")


def test_force_utf8_console_lets_the_terminal_sink_write_any_record():
    stdout, stderr = _legacy_stream(), _legacy_stream()
    with patch.object(sys, "stdout", stdout), patch.object(sys, "stderr", stderr):
        logging_utils.force_utf8_console()
        handler_id = logger.add(
            sys.stdout, format=logging_utils.format_log_record, colorize=False
        )
        try:
            logger.info(MESSAGE)
        finally:
            logger.remove(handler_id)
        stdout.flush()
        stderr.flush()

    assert (stdout.encoding, stderr.encoding) == ("utf-8", "utf-8")
    assert MESSAGE in stdout.buffer.getvalue().decode("utf-8")
    # Loguru reports a record it could not write on stderr.
    assert stderr.buffer.getvalue() == b""


def test_force_utf8_console_skips_streams_it_cannot_switch():
    # pythonw has no console streams, a replaced stream may have no
    # reconfigure(), and a closed one raises ValueError. The other stream is
    # still switched.
    closed = _legacy_stream()
    closed.close()
    for unusable in (None, io.StringIO(), closed):
        stderr = _legacy_stream()
        with patch.object(sys, "stdout", unusable), patch.object(sys, "stderr", stderr):
            logging_utils.force_utf8_console()
        assert stderr.encoding == "utf-8"


@pytest.mark.parametrize("code_page", ["cp1252", "cp936"])
def test_app_config_keeps_log_records_the_code_page_cannot_encode(
    tmp_path, code_page
):
    """
    The API, the WebUI and the CLI all import app.config first. When their
    output goes to a file or pipe on Windows, Python encodes it in the ANSI
    code page, which PYTHONIOENCODING reproduces on any OS. Loguru dropped
    every record that code page cannot encode and printed "Logging error in
    Loguru Handler" in its place.
    """
    code = (
        "from app.config import config; from loguru import logger; "
        f"logger.info({MESSAGE!r})"
    )
    run = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=dict(os.environ, MPT_HOME=str(tmp_path), PYTHONIOENCODING=code_page),
        capture_output=True,
        check=True,
        timeout=60,
    )

    stderr = run.stderr.decode("utf-8", errors="replace")
    assert "Logging error" not in stderr
    assert MESSAGE in run.stdout.decode("utf-8"), stderr
