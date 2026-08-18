from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.health_asset_integrity import (  # noqa: E402
    GitInspectionError,
    GitInspector,
    audit_health_assets,
    ensure_external_output,
    verify_report_bundle,
    write_report_bundle,
)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="strict")
    parser = argparse.ArgumentParser(description="Read-only health asset integrity audit")
    subparsers = parser.add_subparsers(dest="command", required=True)
    audit = subparsers.add_parser("audit")
    audit.add_argument("--repo", required=True, type=Path)
    audit.add_argument("--output-parent", required=True, type=Path)
    audit.add_argument("--audit-id", required=True)
    audit.add_argument("--remote", default="personal")
    audit.add_argument(
        "--remote-ref", default="refs/heads/feature/health-content-system"
    )
    verify = subparsers.add_parser("verify")
    verify.add_argument("--bundle", required=True, type=Path)
    verify.add_argument("--audit-id", required=True)
    verify.add_argument("--expected-manifest-sha256")
    args = parser.parse_args()
    try:
        if args.command == "verify":
            manifest = verify_report_bundle(
                args.bundle, args.audit_id, args.expected_manifest_sha256
            )
            print(
                json.dumps(
                    {
                        "status": "verified",
                        "bundle": str(args.bundle.resolve()),
                        "audit_id": manifest["audit_id"],
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        output_parent = ensure_external_output(args.repo, args.output_parent)
        report = audit_health_assets(
            GitInspector(args.repo), remote=args.remote, remote_ref=args.remote_ref
        )
        output_parent = ensure_external_output(args.repo, output_parent)
        bundle = write_report_bundle(output_parent, args.audit_id, report)
    except (GitInspectionError, OSError) as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False))
        return 3
    exit_code = 0 if report.summary["audit_complete"] else 4
    status = "complete" if exit_code == 0 else "incomplete"
    print(json.dumps({"status": status, "bundle": str(bundle)}, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
