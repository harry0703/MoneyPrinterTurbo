# Project context

This repository is upstream MoneyPrinterTurbo plus a scheduled publishing
operation built on top of it. The upstream READMEs describe the generator; they
say nothing about the operation, which is what almost all recent work concerns.

**Read `docs/RUNBOOK.md` before touching anything that publishes.** It carries
the schedule, the network path, the session procedure, and the incidents that
shaped the current design. Several obvious-looking "improvements" have already
cost live accounts.

## What runs

Two independent pipelines, four Instagram accounts, one server.

| Pipeline | Accounts | Entry point | Cron (UTC) |
|---|---|---|---|
| Content plan | why, waypoint, creature | `scripts/daily_run.py` | `0 10 * * *` |
| Brainrot | brainrot | `scripts/brainrot_run.py` | `30 19,23,3,7,11,15 * * *` |

Server: `ubuntu@141.253.101.226`, project at `~/MoneyPrinterTurbo`.
**The server clock is UTC; the operator is in Paris.** Every cron hour in this
repo is UTC and is one or two hours behind what the operator means.

## Rules that are not negotiable

- **Never retry a 429.** The penalty is account-level. `classify_error()` in
  `scripts/instagram_worker.py` checks rate limits first, on purpose.
- **Never fall back to password login.** The private API rejects instagrapi's
  app version, so it cannot succeed, and the attempt burns the exit IP.
  A dead session is re-imported by a human, never retried by the machine.
- **Publishing runs on the server, not locally.** The local checkout has no
  `[instagram]` config, and the session files live where the cron runs.
- **Stop the WebUI before hand-editing `config.toml`.** It holds the config it
  read at startup and rewrites the whole file on save.
- Secrets — passwords, session ids, WireGuard keys — never enter this repo.
  `*.conf` and `resource/brainrotVideo/` are gitignored for that reason.

## Conventions

Commits follow Conventional Commits, and the body explains *why*, not what.
Code comments are in Chinese, matching upstream. Tests carry the reasoning for
invariants that are expensive to rediscover; several encode a past incident.
Run the full suite (`uv run python -m pytest test -q`) before pushing —
it takes about three minutes.
