# Health asset integrity audit runbook

This audit is read-only and fail-closed. It records evidence in a new directory outside the audited repository; it does not restore, delete, move, stage, or commit assets.

## Production command

Run from the isolated implementation worktree. The output parent and audit ID below are fixed for this audit and must not exist before execution.

```powershell
$python='E:\MoneyPrinterTurbo-3期\MoneyPrinterTurbo\.venv\Scripts\python.exe'
& $python '09_泛健康日更/scripts/audit_health_assets.py' audit `
  --repo 'E:\MoneyPrinterTurbo-3期\MoneyPrinterTurbo\.worktrees\health-content-system' `
  --output-parent 'E:\MoneyPrinterTurbo-3期\audit-evidence' `
  --audit-id 'HCAS-20260818-01' `
  --remote personal `
  --remote-ref 'refs/heads/feature/health-content-system'
```

## Immutable four-file bundle

- `audit.json` — UTF-8 JSON using report schema `health_asset_integrity.v1`; contains the complete structured evidence and no blob contents.
- `deleted-assets.csv` — UTF-8 CSV with one fixed column for every `DeletedAsset` field, ordered deterministically by repository path.
- `audit-summary.md` — UTF-8 Markdown summary of counts, episode rows, remote/LFS/large-blob evidence, mutation guard, and all three non-preferred user decision options.
- `bundle-manifest.json` — UTF-8 JSON using schema `health-asset-integrity-bundle-v1`; binds the SHA-256 and byte size of the other three files to the audit ID and report schema.

The final audit directory is published only after all four files are exclusively created and flushed. A failed write remains under `.<audit-id>.staging` as incomplete evidence and must not be consumed as a bundle. An existing final audit ID or staging ID is never overwritten or reused.

## Exit codes

- `0` — all requested local, LFS, and remote evidence is complete; the bundle is published.
- `3` — safety or operational failure, including an in-repository output path, unsafe path component, invalid audit ID, or existing output; no final bundle is published.
- `4` — requested evidence is incomplete, commonly because remote or LFS evidence is unavailable; the bundle is published with `summary.audit_complete=false`, and no disposition is preferred.

## Non-mutation rules

Every Git and Git LFS subprocess uses `GIT_OPTIONAL_LOCKS=0`. Do not use `git checkout`, `git restore`, `git reset`, `git clean`, `git fetch`, `git pull`, `git lfs pull`, `git add`, `git commit`, `git rm`, `git update-index`, or any command that changes repository configuration, refs, the index, the worktree, or LFS objects. Remote evidence uses `git ls-remote` only and never fetches.

Only the user may choose a disposition after reading and independently validating the report. The three options are evidence labels, not recommendations; exit code `4` blocks any disposition recommendation.
