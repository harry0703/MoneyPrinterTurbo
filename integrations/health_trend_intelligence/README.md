# Health Trend Intelligence

This independent project provides a deterministic, offline foundation for health
trend intelligence exchange.

During this phase it processes synthetic/offline JSONL only. It never launches
MediaCrawler, imports it as a Python package, or collects live platform data.
The Task 8 end-to-end check generates exactly 300 synthetic posts and 200
synthetic comments across dy/xhs, exercises Tasks 1–7, compares two clean
Curated/Approved trees by relative path, byte count, and SHA-256, and imports the
externally anchored Approved package into a temporary fake MoneyPrinterTurbo
repository.

This proves only the offline contract and reproducibility of synthetic fixtures.
The ten synthetic candidates are not a real trend ranking, medical evidence,
medical review, or a claim of real human selection. No media is downloaded and
nothing is automatically published. Raw retention is report-only.

The read-only boundary CLI requires an explicit audit profile and includes it
in canonical JSON. `current-worktree-audit` pins the reviewed Task 8 base,
exact 240-path deletion digest, current local `config.toml` identity, disclosed
legacy-cache roots, and MediaCrawler location/commit. Its PASS protects only
the reviewed dirty worktree. `clean-checkout-validation` instead requires a
clean committed checkout and zero manual-pack worktree deletions. It does not
read or hash a local ignored `config.toml`, does not inherit current-worktree
legacy-cache exclusions, and accepts operator-supplied external synthetic
roots and a MediaCrawler root whose fixed commit and clean status are verified.
Commit scope and expected counts/hashes are code-owned, never caller-supplied.

Both profiles verify repository-wide Git index/porcelain plus on-disk Raw
state, recursive protected config/dependency paths, lexical and resolved path
chains, and every regular artifact file. Current-profile scan exclusions are a
versioned set of exact repository-relative metadata/venv/legacy-test-cache
roots; no basename, prefix, or substring can create a new exclusion. Every
ordinary file below `app/config/` is protected regardless of extension, apart
from the exact `app/config/__pycache__` root. JSON/JSONL keys are parsed as unique NFC
keys, then NFKC/casefold/separator-normalized for a bounded credential-key
policy covering HMAC, signing, private, encryption and access keys without
treating ordinary hash/SHA-256/manifest-digest metadata as credentials. Media
extensions and common file signatures are rejected.
Missing or unverifiable checks fail closed with no payload or supplied path in
the error output. Synthetic phone/email-shaped values alone are not claimed to
be real credentials.

The Approved producer and the standard-library MoneyPrinterTurbo consumer
enforce the same selection contract: exactly one
`medical_claim_unverified` marker per candidate, no affirmative medical or
clinical verification status, exact dy/xhs batch coverage, strict field/type,
rank/topic/list/disclaimer rules, and identical missing-sentinel rejection.
Explicit negative, pending, and unverified status statements remain valid.

Run the focused synthetic contract from the MoneyPrinterTurbo repository root:

```powershell
$env:UV_CACHE_DIR = Join-Path $env:TEMP 'hti-task8-uv-cache'
uv run --project integrations/health_trend_intelligence pytest integrations/health_trend_intelligence/tests/test_foundation_e2e.py -q --basetemp (Join-Path $env:TEMP 'hti-task8-pytest') -p no:cacheprovider
```

See [RUNBOOK.md](RUNBOOK.md) for the exact offline registration, curation,
Approved build/verify, externally anchored Task 7 import, boundary report,
retention, recovery, and synthetic cleanup commands.
