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

Run the focused synthetic contract from the MoneyPrinterTurbo repository root:

```powershell
$env:UV_CACHE_DIR = Join-Path $env:TEMP 'hti-task8-uv-cache'
uv run --project integrations/health_trend_intelligence pytest integrations/health_trend_intelligence/tests/test_foundation_e2e.py -q --basetemp (Join-Path $env:TEMP 'hti-task8-pytest') -p no:cacheprovider
```

See [RUNBOOK.md](RUNBOOK.md) for the exact offline registration, curation,
Approved build/verify, externally anchored Task 7 import, boundary report,
retention, recovery, and synthetic cleanup commands.
