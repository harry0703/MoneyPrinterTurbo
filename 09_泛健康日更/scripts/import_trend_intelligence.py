from __future__ import annotations

import argparse
import sys
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.health_trend_exchange import (  # noqa: E402
    TrendExchangeError,
    import_trend_exchange,
    verify_trend_exchange,
)


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        self.exit(3, "rejected reason=invalid_arguments\n")


def _parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(
        description="Verify or import approved trend intelligence"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("verify", "import"):
        command = commands.add_parser(name)
        command.add_argument("--source", required=True)
        command.add_argument("--expected-manifest-sha256", required=True)
        if name == "import":
            command.add_argument("--repo-root", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "verify":
            result = verify_trend_exchange(
                Path(args.source), args.expected_manifest_sha256
            )
            print(
                f"verified batch={result.batch_id} version={result.version} "
                f"candidates={result.candidate_count}"
            )
        else:
            destination = import_trend_exchange(
                Path(args.source),
                Path(args.repo_root),
                args.expected_manifest_sha256,
            )
            print(f"imported batch={destination.parent.name} version={destination.name}")
        return 0
    except (FileExistsError, OSError, TrendExchangeError) as error:
        reason = (
            error.reason_code
            if isinstance(error, TrendExchangeError)
            else "destination_already_exists"
            if isinstance(error, FileExistsError)
            else "filesystem_rejected"
        )
        print(f"rejected reason={reason}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
