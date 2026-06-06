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

## 3. Install + enable the timers

```bash
deploy/install.sh        # renders the units with this checkout's path/user/uv, installs
                         # to /etc/systemd/system (sudo), daemon-reload, enable --now
```

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
