# Deploy — running the tournament on an always-on server

The competition runs from a Linux box via two systemd timers (DESIGN §11):

| Timer | Runs | Cadence | Purpose |
|---|---|---|---|
| `wc-tick.timer` | `orchestrate tick` | every 30 min | ingest results → settle → post-match → resolve bracket → decay → brief → predict/bet |
| `wc-odds.timer` | `ingest odds` | every 6 h | poll The Odds API for 1X2 consensus odds (1 credit/poll) |

The tick is **idempotent and lazy** — every run only does work that is due, so a missed,
overlapping, or extra run is harmless. Odds polling is deliberately separate and infrequent
to stay inside the free 500/mo quota (4/day ≈ 120/mo).

> Git carries **code only**. The real `.env` (API keys) and `worldcup.db` (live state) live
> **only on the server** — never commit them. Develop on the Mac, deploy by pull.

---

## 1. First-time deploy

```bash
# Prerequisites: git, and uv (https://docs.astral.sh/uv/). Python 3.11 is fetched by uv.
git clone https://github.com/thecr7guy2/worldcup-agents.git
cd worldcup-agents

uv sync                              # build the venv from uv.lock
cp .env.example .env                 # then edit .env: ODDS_API_KEY + OPENROUTER_API_KEY
                                     # (OpenRouter needs a funded balance — web search is paid)

uv run python -m worldcup_agents.ingest seed     # 48 teams + 104 fixtures into worldcup.db
uv run python -m worldcup_agents.ingest odds      # first odds snapshot (spends 1 credit)
```

## 2. Smoke test before scheduling (catches a bad .env / wrong cwd)

```bash
uv run python -m worldcup_agents.orchestrate status   # what is due now (read-only, no LLM)
uv run python -m worldcup_agents.bracket status       # standings + unresolved KO labels
```

Before June 11 every window is in the future, so `status` should show little or nothing due
and **no errors**. A keys/cwd problem surfaces here, not at 3 a.m. on matchday.

### 2b. End-to-end dry run (prove the LLM path — do this once before June 11)

`status` is free but only checks scheduling. The expensive briefing → predict → bet path
never actually fires until the first real fixture enters its window — i.e. live, on
matchday. Force it now, in isolation, so a malformed-output / token / slug problem has runway:

```bash
uv run python scripts/dry_run.py --models 1   # cheap: briefing + 1 model (a few cents)
uv run python scripts/dry_run.py              # full: briefing + all competitors
```

It builds a **throwaway** DB (never touches `worldcup.db`), seeds one synthetic fixture, and
prints the briefing, every model's prediction + bet + reasoning, per-model failures, and the
cost/token telemetry. It **spends real OpenRouter credit** (web search + reasoning). A green
run means every competitor produced a valid prediction + bet against the live models.

## 3. Install + enable the timers

```bash
deploy/install.sh        # renders the units with this checkout's path/user/uv, installs
                         # to /etc/systemd/system, daemon-reload, enable --now
```

> Run it as **yourself**, not `sudo deploy/install.sh`. The script elevates internally only
> where root is needed; running the whole thing under sudo makes `uv` resolve as root
> (`/root/.local/bin/uv`) and the units come out broken. (It now refuses sudo and tells you.)

Want to eyeball the units first? Render without touching the system:

```bash
deploy/install.sh --render /tmp/wc-units && cat /tmp/wc-units/*
```

## 4. Verify it's live

```bash
systemctl list-timers 'wc-*'                       # next/last fire times
systemd-analyze verify /etc/systemd/system/wc-*.service   # unit sanity
sudo systemctl start wc-tick.service               # force one tick now
journalctl -u wc-tick.service -n 30 --no-pager     # see its summary line + any ERRORs
```

A healthy tick logs e.g.
`tick — results:0 settled:0 postmatch:0 resolved:0 decay:0 briefed:2 predicted:1`.

---

## Operations

- **Watch live:** `journalctl -u wc-tick.service -f`
- **Run a tick by hand:** `sudo systemctl start wc-tick.service`
- **Poll odds by hand:** `sudo systemctl start wc-odds.service`
- **Pause / resume everything:** `sudo systemctl disable --now wc-tick.timer wc-odds.timer`
  then `sudo systemctl enable --now wc-tick.timer wc-odds.timer`
- **Leaderboards:** `uv run python -m worldcup_agents.leaderboard`
- **Update code mid-tournament:** `git pull && uv sync` (the timers pick up the new code on
  their next fire; `--no-sync` in the units means deps come only from your explicit `uv sync`).
- **Backup state:** copy `worldcup.db` somewhere safe periodically — it is the entire
  competition.

## Tuning cadence

Edit `OnCalendar` in the `.timer` files, re-run `deploy/install.sh`, done.
- Tick more often: `OnCalendar=*:0/15` (every 15 min).
- Fresher odds: `OnCalendar=00/4:00` (every 4 h, 6/day, still < 500/mo).

## Notes / gotchas

- **`WorkingDirectory` is essential** — `.env` and `worldcup.db` are resolved relative to it.
  The installer hard-codes it to this checkout; if you move the repo, re-run the installer.
- **`uv` path** — the units use the `uv` found on your PATH at install time (falling back to
  `~/.local/bin/uv`). If `uv` later moves, re-run the installer.
- **Single gateway** — all models go through OpenRouter; on an outage the tick logs errors and
  retries the same due work next fire (nothing is lost — work is keyed off DB state, not time).

---

# The showcase site (the Arena)

A public Next.js site that reads the live DB read-only and renders it as a video-game-style
showcase (agent profiles, fixtures with flags, leaderboards, token/cost telemetry). Two
long-running services, separate from the tournament timers above:

| Service | Process | Bind | Role |
|---|---|---|---|
| `wc-api` | `uvicorn worldcup_agents.web.app:app` | 127.0.0.1:8001 | read-only JSON API over `worldcup.db` |
| `wc-web` | `next start` | 0.0.0.0:3000 | the site; proxies `/api/*` to wc-api |

## One-time: install Node

The frontend needs Node 20+ at build and run time (the only non-Python dependency the server
gains). Any install works; e.g. NodeSource, or a tarball symlinked into `~/.local/bin`.

## Deploy / update

```bash
git pull && uv sync                      # API deps (fastapi, uvicorn) come from uv.lock
cd web && npm ci && npm run build        # production build (required before `next start`)
cd .. && deploy/install-web.sh           # render + install + enable wc-api and wc-web
```

The installer refuses to proceed if `web/.next` is missing (build first). To review the units
without touching the system: `deploy/install-web.sh --render /tmp/units`.

After a code change, redeploy with the three lines above (re-running `install-web.sh` is safe
and also restarts the services), or just `sudo systemctl restart wc-api wc-web` if only data
changed.

## Verify

```bash
systemctl status wc-api.service wc-web.service --no-pager
curl -s localhost:8001/api/health          # {"ok": true, ...}
curl -s localhost:3000/api/overview | head # proxy + API both up
```

Open `http://<server-ip>:3000` on the LAN. The API stays private on localhost; only the Next
server is exposed. The site degrades gracefully before kickoff and fills in automatically as
predictions, bets, results, and telemetry land — no redeploy needed for new data.

## Secret: the Human Challenger

A hidden 8th competitor lets a human bet alongside the AIs under the same rules (same $1M,
25% cap, idle decay, bust/re-buy, settled on the 90' result, **bets lock ~50 min before
kickoff** like the AIs). He is excluded from every public board until `CHALLENGER_PUBLIC` is
flipped to `True` in `config.py` (intended for after the tournament).

Enable it by setting a passphrase in `.env` (empty = feature off, all `/api/challenger/*`
routes 404):

```bash
CHALLENGER_KEY=<your-passphrase>
CHALLENGER_NAME=You            # optional: the human's leaderboard name
```

The `is_human` column is added automatically (idempotent migration in `db.init_db`; the tick
applies it on its next run, or run it once now):

```bash
uv run --no-sync python -c "from worldcup_agents import db; c=db.connect(); db.init_db(c)"
```

**Access:** on the site, type the Konami code (↑ ↑ ↓ ↓ ← → ← → B A) to reveal `/challenger`,
then enter the passphrase. There is no visible link. Each match is a two-step flow that mirrors
the AIs — predict (odds hidden) then bet (odds shown). Restart `wc-api` after changing the key.
