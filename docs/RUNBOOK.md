# Runbook

Everything an operator or a fresh session needs to run the publishing
operation. Written 2026-08-21; the "current state" section is the only part
that goes stale on its own.

---

## 1. The machine and the network path

```
Oracle ARM VM          ubuntu@141.253.101.226:~/MoneyPrinterTurbo
Clock                  UTC  (operator is Europe/Paris, UTC+2 summer)
Instagram traffic      SOCKS5 127.0.0.1:1080 (dante)
                         └─ external: wg interface "fbx"
                              └─ friend's Freebox, exit IP 82.230.158.147
```

All four accounts publish through that single exit. The WireGuard config uses
`Table = off`, so it installs no routes and cannot cut SSH; only traffic that
dante sends is tunnelled.

**The shared exit is a known weakness.** Four accounts behind one residential
IP is an aggregation signal we cannot remove without a second exit.

### Timezone

Cron on this box has no `CRON_TZ` support (checked: the binary has no such
symbol), so entries are UTC and were written by subtracting two hours from the
Paris time the operator asked for.

**At the end of October, Paris moves to UTC+1 and every cron hour must lose one
hour** or the whole schedule drifts. This is the one dated maintenance item in
the project.

---

## 2. The two pipelines

### Content plan — why, waypoint, creature

One video per account per day, generated from `content_plan.json`.

```
content_plan.json      subjects, per-account defaults, outro, caption, schedule
scripts/build_content_plan.py   regenerates the plan and the captions
run_plan.py            renders and publishes ONE entry
scripts/daily_run.py   runs the three accounts in a random order, spaced out
```

`daily_run.py` is one script for three accounts rather than three crons: a
render takes upwards of ten minutes and the machine holds a single generation
lock, so three separate crons would collide and silently drop a post. The
delays are random so an account does not publish at the same clock time daily.

### Brainrot — triple.t.polyester

A throwaway test account, six posts a day. Format: a bait clip, then a Spiderman
edit invading the frame, then the edit full screen.

```
resource/brainrotVideo/bait/       operator-supplied clips, gitignored
resource/brainrotVideo/template/   the edit spliced in
brainrot_texts.json                card lines + the fixed caption
scripts/make_brainrot.py           renders one video
scripts/brainrot_run.py            renders and publishes one, for cron
```

Four variants, drawn by weight: classic 15%, sweep 25%, flash 30%, rush 30%.
`classic` and `rush` start the invasion at 3.5s; `flash` and `sweep` keep 7s
because their cameos are scheduled at 4.5s and 5-6s and are only drawn before
the invasion starts — a shorter lead-in drops them silently. A test pins this.

Bait clips are consumed in name order and never reused: a repeated clip is what
a platform reads as templated production. When the pool runs out the script
stops with a message rather than recycling.

The caption is one fixed block of Japanese text on every post, chosen by the
operator. Set in `brainrot_texts.json` under `caption.fixed`; clearing it falls
back to a per-video composed caption.

---

## 3. Sessions — the fragile part

Authentication is by **browser session id**, never by password. The private API
validates a client version number that instagrapi cannot fabricate, so password
login is guaranteed to fail and only burns the exit IP.

### The rule that made them survive

A session must be **created from the same network it will be used from**.
Sessions born in the operator's home browser and used from the server's exit IP
died repeatedly, sometimes within hours. The first night all four survived was
the first night they were created through the tunnel.

### Import procedure

1. Open the tunnel, and leave it open:
   ```bash
   ssh -i ~/.ssh/id_ed25519 -o ServerAliveInterval=60 \
       -L 1080:127.0.0.1:1080 ubuntu@141.253.101.226
   ```
2. In a **separate Firefox profile** (`firefox -P`), set a manual proxy:
   SOCKS host `127.0.0.1`, port `1080`, SOCKS v5, and tick "proxy DNS when
   using SOCKS v5". Firefox never silently bypasses a configured proxy, so a
   page that loads is a page that went through the tunnel.
3. Confirm `https://api.ipify.org` shows **82.230.158.147**. If not, stop.
4. Log in. Copy the `sessionid` cookie (F12 → Storage → Cookies).
5. **On the server**, not locally:
   ```bash
   uv run python publish_instagram.py --import-session "<value>" --account why
   ```
6. For further accounts use Instagram's "add account", never "log out".
7. `uv run python publish_instagram.py --check-all`

**Never click "log out".** It is the one action that revokes a session id
server-side. Closing the tab is fine.

---

## 4. Daily commands

All on the server, from `~/MoneyPrinterTurbo`.

```bash
uv run python publish_instagram.py --check-all        # before the noon cron
uv run python publish_instagram.py --stats            # numbers, no browser
uv run python scripts/daily_run.py --dry-run          # today's plan
uv run python scripts/brainrot_run.py --dry-run       # next caption
uv run python scripts/make_brainrot.py --list         # bait stock
crontab -l
tail -f storage/logs/cron-brainrot.log
```

Adding bait clips needs no command if they are dropped straight into
`resource/brainrotVideo/bait/` on the server. `scripts/sync_bait.py` is only for
pushing them from the operator's PC.

### State files

```
storage/brainrot_state.json        used_bait, text_index, pending, published
storage/content_plan_state.json    per-entry status and urls
storage/instagram_session_*.json   one per account
storage/instagram_uploads_*.json   rate-limit history, 3/hour and 10/day
storage/logs/
```

`pending` in the brainrot state is a render that succeeded but failed to
publish. The next slot publishes it instead of making a new one — the bait was
already spent, and there are only ever a couple of dozen clips.

---

## 5. Incidents worth not repeating

**429 amplification.** A 429's message contains "Max retries exceeded", which
matched the transient-error markers, so rate limits were retried three times and
urllib3 retried them again underneath. `classify_error()` now checks rate limits
first and `_calm_retries()` removes 429 from the HTTP-layer retry list.

**Password fallback on a dead session.** Guaranteed to fail and it burned the
exit IP. The worker now raises `SessionExpired` with the recovery command.

**Reading stats killed three sessions.** A stats page was added that called the
private mobile API for all four accounts. The three plan accounts authenticated
successfully, the stats endpoints answered `login_required` for exactly those
three, and two minutes later their sessions were rejected outright. The fourth,
taking identical calls, was unaffected. Causation was never established.

The feature is now restricted to the throwaway account via `STATS_ACCOUNTS` in
`app/services/instagram.py`, and prefers the web GraphQL endpoint — though that
path currently fails to parse and falls back to the private one, so the
restriction is the only protection actually in effect. **Emptying that tuple
before the test account has gone several days unaffected is how this incident
repeats.**

**Blank text cards.** A refactor introduced a local variable for the card line
but left three call sites reading the command-line argument, so renders came out
with an empty card. Logs looked healthy; only opening the video showed it.
Anything that only manifests in the rendered frames needs a test, not a log
line.

**Relative asset paths.** Default paths were resolved against the working
directory. Cron happened to `cd` first, so it worked, and broke silently
anywhere else. All asset paths now go through `project_root()`.

**config.toml emptied itself.** The WebUI holds the config it read at startup
and rewrites the whole file on save, discarding hand edits made meanwhile.
Stop the service, edit, start.

---

## 6. Current state, 2026-08-21

Sessions: four, all valid, all created through the tunnel on 2026-08-20 night.
This is the first configuration that survived a night; treat it as unproven
rather than solved.

Plan accounts start today at 12:00 Paris, from why-007, creature-004,
waypoint-003.

Brainrot has published four reels (one manual, three by cron), of which one —
`DcR-TNdsiUy` — is no longer on the account and was either deleted by the
operator or taken down. Roughly 125 plays each, 1 like, 0 followers. Bait stock
is 19 unused of 22, about three days at six a day.

Open questions:

- Was the missing reel a takedown? If the platform is removing the Spiderman
  footage or its music, the format has a ceiling that view counts will not show.
- Does the stats path cost sessions? Being tested on the throwaway account.
- TikTok is not started. Three routes exist: the official Content Posting API
  (needs an audit, otherwise posts land in drafts), upload-post.com (already
  wired at `app/services/upload_post.py`, disabled, paid, untested), or browser
  automation. Detection there is harsher than on Instagram.

---

## 7. If something breaks and no help is available

Written to be executed by a person with a terminal and no assistant. Every
command runs on the server, from `~/MoneyPrinterTurbo`, unless stated.

### First, look

```bash
tail -50 storage/logs/cron-brainrot.log
tail -50 storage/logs/cron.log
ls -la storage/logs/
crontab -l
uv run python publish_instagram.py --check-all
```

`--check-all` answers the most common question. Four `ok` lines means the
accounts are fine and the problem is elsewhere.

### "An account stopped posting"

Almost always a dead session. The line to look for is `stored session was
rejected`. Fix it with the import procedure in section 3 — the tunnel matters,
a session imported from a home browser is the failure being repeated.

Nothing is lost while a session is down. The content plan leaves the entry
unmarked and picks it up next run; brainrot keeps the rendered file as
`pending` and publishes it at the next slot.

### "Nothing published at all today"

```bash
grep CRON /var/log/syslog | tail -20
```

If cron did not fire, check the clock: `date -u`. **Every cron hour in this
repo is UTC.** A schedule that looks two hours off in October is the daylight
saving change described in section 1, not a bug.

To run a pipeline by hand right now:

```bash
uv run python scripts/daily_run.py --next        # the three plan accounts
uv run python scripts/brainrot_run.py --no-jitter  # one brainrot video
```

### "It says the bait pool is exhausted"

Expected, not broken. Drop more clips into
`resource/brainrotVideo/bait/` on the server; nothing else to run. Check with
`uv run python scripts/make_brainrot.py --list`.

### "hourly limit reached" / "429"

**Do nothing.** Both are working as intended — the first is our own guard
(3/hour, 10/day per account), the second is Instagram's. Wait. Retrying a 429
is the single most damaging thing that can be done here, and the penalty lands
on the account, not the request.

### "Stop everything now"

```bash
crontab -l > ~/crontab.backup
crontab -r
```

Restore later with `crontab ~/crontab.backup`. Removing the crontab stops all
publishing without touching any state; the pipelines resume where they left off.

### Publish one specific file by hand

```bash
uv run python publish_instagram.py \
  --video storage/brainrot/<file>.mp4 \
  --caption "$(python3 -c "import json;print(json.load(open('brainrot_texts.json'))['caption']['fixed'])")" \
  --account brainrot
```

### Working with a different assistant

An agent with access to this checkout needs nothing beyond `CLAUDE.md`,
`AGENTS.md` and this file — point it at them and it has the full picture.

A chat-only assistant with no repository access is a different situation. Paste
`CLAUDE.md` and this runbook, plus the specific file being changed; it can then
reason usefully but cannot verify anything. Do not let it invent commands for
the publishing path. Everything that path legitimately needs is already written
above, and a plausible-looking improvised command is how accounts get lost.
