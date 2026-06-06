# Slice: Deployment + scheduling (systemd timers on the Linux server)

**Status:** PLANNED — ready for execution.
**Read first:** `tasks/DESIGN.md §11` (deployment & runtime — source of truth) and the
`Deployment` section of `CLAUDE.md`. Kickoff is **2026-06-11**; this must be live + dry-run
on the server a few days before.

---

## 0. Why this slice exists

The whole pipeline is built and verified, but nothing *runs it on a schedule*. DESIGN §11
calls for an always-on Linux box driving the matchday pipeline via **systemd timers**. This
slice ships the deploy artifacts (units + installer + runbook) so the tournament runs
unattended across the ~6-week event.

Two independent scheduled jobs (DESIGN §3, "odds polling is a SEPARATE, less-frequent job"):

| Job | Command | Cadence | Why |
|---|---|---|---|
| **tick** | `orchestrate tick` | every 30 min | catch the bet window (3 h pre-KO) + result delay (2.5 h post-KO) promptly; no-op + free when nothing is due; idempotent so overlap/missed runs are safe |
| **odds** | `ingest odds` | every 6 h | 1 credit/poll; 4/day ≈ 120/mo, well under The Odds API 500/mo free quota |

### Scope boundary
- **IN:** four systemd units (tick + odds, each a `.service` + `.timer`), a render/install
  script, a deploy runbook, and a root-README pointer. Offline-verifiable by *rendering*
  the units on the Mac (can't run systemd here).
- **OUT:** the eliminated-competitor skip (separate follow-up); a simulated end-to-end
  dry-run harness (separate slice); any code/logic change to the pipeline itself.

---

## 1. Design decisions (pre-made)

- **System units** (`/etc/systemd/system`, `User=`) not `--user` units — survives reboot
  with no `loginctl enable-linger` gotcha. Installer uses `sudo` only for the copy + enable.
- **`uv run --no-sync`** in `ExecStart` — the env is built once at deploy (`uv sync`); a
  scheduled job must never re-resolve/upgrade deps mid-tournament. Deterministic + offline.
- **`WorkingDirectory=<repo>`** is load-bearing: `config.Settings` reads `.env` and `db.py`
  defaults the DB to `worldcup.db`, both **relative to cwd**. Wrong cwd → no keys, wrong DB.
- **`Type=oneshot`** + timer: a still-running tick is not retriggered (systemd skips), and the
  tick is idempotent anyway, so no overlap/locking needed. `TimeoutStartSec=3600` for the
  tick (a busy matchday briefs many fixtures via web search), `600` for odds.
- **`Persistent=true`** on both timers → a run missed while the box was off fires on wake.
- **Parameterized units** with `__REPO__` / `__USER__` / `__UV__` tokens; the installer
  detects real values and substitutes. Single source of truth, reviewable in-repo.
- **Logs** go to journald (the tick already prints a one-line summary + `ERROR` lines).

---

## 2. Files

- `deploy/wc-tick.service`, `deploy/wc-tick.timer`
- `deploy/wc-odds.service`, `deploy/wc-odds.timer`
- `deploy/install.sh` — `--render <dir>` (no sudo, for review) | default = install + enable.
- `deploy/README.md` — the runbook (clone → uv sync → .env → seed + first odds → smoke →
  install timers → verify → operations).
- `README.md` — add a "Run the tournament (server)" pointer to `deploy/`.

---

## 3. Acceptance criteria

1. `deploy/install.sh --render /tmp/wc-units` writes four units with **every** `__TOKEN__`
   substituted to a concrete repo path / user / uv path (no `__…__` left).
2. Rendered units are well-formed: tick service runs `… orchestrate tick`, odds service runs
   `… ingest odds`; both set `WorkingDirectory` to the repo and `User`; timers have
   `[Install] WantedBy=timers.target`, `Persistent=true`, and the documented `OnCalendar`.
3. `bash -n deploy/install.sh` passes; the script is `chmod +x`.
4. `deploy/README.md` covers: prerequisites, deploy steps, the seed + first odds poll, a
   pre-install smoke test (`orchestrate status`, one `ingest odds`), install, verify
   (`systemctl list-timers`, `journalctl -u wc-tick`), operations (manual tick, pause/resume),
   and the cadence/quota rationale.
5. No change to `src/` (deploy-only slice); existing verifications still PASS.

---

## 4. Verification (offline, on the Mac)

```bash
deploy/install.sh --render /tmp/wc-units
grep -R '__' /tmp/wc-units && echo "FAIL: unsubstituted token" || echo "OK: all tokens filled"
cat /tmp/wc-units/*.service /tmp/wc-units/*.timer
bash -n deploy/install.sh && echo "install.sh syntax OK"
```
Real systemd verification happens on the server (`systemd-analyze verify`, `list-timers`) —
documented in the runbook as the post-deploy check.

## 5. Results (filled 2026-06-06)
- **Files touched:**
  - `deploy/wc-tick.service` + `deploy/wc-tick.timer` — `orchestrate tick`, every 30 min.
  - `deploy/wc-odds.service` + `deploy/wc-odds.timer` — `ingest odds`, every 6 h.
  - `deploy/install.sh` — `--render DIR` (offline review) | default install to
    `/etc/systemd/system` + `daemon-reload` + `enable --now`. Detects repo/user/uv.
  - `deploy/README.md` — full runbook (deploy, smoke, install, verify, operations, tuning).
  - `README.md` — added "Run the tournament (server)" pointer to `deploy/`.
- **How verified (offline, Mac):** `deploy/install.sh --render /tmp/wc-units` → 4 units,
  **zero** `__…__` tokens left, all paths/user substituted; units well-formed (correct
  `ExecStart`, `WorkingDirectory`, `User`, `Persistent=true`, `[Install]`). `bash -n
  deploy/install.sh` OK; installer is `+x`. No `src/` change → pipeline verifications
  unaffected. Real systemd checks (`systemd-analyze verify`, `systemctl list-timers`) are
  documented as the on-server post-deploy step.
- **Follow-ups logged:** server-side deploy + dry-run still to be done by the user before
  June 11 (runbook is the checklist); `predict.run_fixture` eliminated-competitor skip and a
  simulated end-to-end dry-run remain open (separate slices).
