"""Stage subtitle artifacts beside their destination before publication."""
from contextlib import contextmanager
import os
import tempfile

from loguru import logger


@contextmanager
def staged_subtitle_file(destination):
    descriptor, staged = tempfile.mkstemp(
        prefix=".subtitle-", suffix=".srt",
        dir=os.path.dirname(os.path.abspath(destination)),
    )
    os.close(descriptor)
    try:
        yield staged
    finally:
        try:
            os.remove(staged)
        except FileNotFoundError:
            pass
        except OSError as cleanup_error:
            logger.warning(f"failed to remove temporary subtitle: {cleanup_error}")


def write_subtitle_file(destination, content):
    with staged_subtitle_file(destination) as staged:
        with open(staged, "w", encoding="utf-8") as output:
            output.write(content)
        os.replace(staged, destination)
