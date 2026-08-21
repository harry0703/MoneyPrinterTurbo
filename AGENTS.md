# Agent context

Canonical context for this repository, for any coding agent.

1. **`CLAUDE.md`** — what runs, where, and the rules that protect live accounts.
2. **`docs/RUNBOOK.md`** — procedures, state files, and the incidents that
   shaped the current design. Section 5 explains why several limits that look
   arbitrary from the code are not; section 7 is what to do when something
   breaks.

Read both before changing anything under `scripts/`, `run_plan.py`,
`publish_instagram.py`, or `app/services/instagram.py`. This repository drives
four live Instagram accounts on a schedule. Mistakes here are not caught by
tests — they are caught by an account going quiet.

The three that have already cost accounts:

- **Never retry a 429.** The penalty is account-level, not request-level.
- **Never fall back to password login.** It cannot succeed and it burns the
  shared exit IP. A dead session is re-imported by a human.
- **Never widen `STATS_ACCOUNTS`** in `app/services/instagram.py` without
  reading section 5 of the runbook first.

Secrets never enter this repository. If a task seems to need one, it is being
done in the wrong place — publishing runs on the server, not on the checkout.
