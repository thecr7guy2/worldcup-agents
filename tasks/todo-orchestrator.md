# Slice: Orchestrator tick — the scheduled pipeline driver

**Status:** IN PROGRESS. **Executor:** Opus.
**Read first:** DESIGN §3 (concurrency / report batch), §4 (temporal integrity), §11 (deployment —
systemd timers). Every stage it sequences is already built + verified (ingest, brief, predict/bet,
result ingestion, settle, decay, leaderboards).

---

## 0. What it is

A coarse, **idempotent** pass invoked by a systemd timer. It reads "what is due now" from fixture
kickoff times + DB state and fans the work out **in temporal-integrity order** (DESIGN §4):
finished matches are settled and folded into the dossiers BEFORE upcoming matches are briefed, so
match N's post-match facts reach N+1's briefing and never N's own.

```
tick(now):
  1. ingest results   matches past kickoff+RESULT_DELAY, still unresolved
  2. settle bets      resolved fixtures that still have unsettled bets
  3. post-match       finished fixtures -> per-team recap + dossier fold (once per team)
  4. idle decay       matchdays fully closed and not yet decayed
  5. brief            scheduled fixtures inside the pre-match window (no briefing yet)
  6. predict + bet    scheduled fixtures inside the bet window (briefing + odds present)
```

## 1. Load-bearing rules

- **Order = temporal integrity.** Settle + post-match + dossier-fold (1-3) run BEFORE brief (5),
  so the freshest facts flow into upcoming briefings; predict/bet (6) is last and only before kickoff.
- **Idempotent + overlap-safe.** Every stage is lazy (skip-if-exists). The tick is safe on any
  cadence and after a crash/restart. Per-fixture failures are caught and logged — one bad match
  never blocks the rest.
- **Dossier fold is the one non-idempotent step** (an LLM rewrite of rolling_form). Guard it with a
  per-`(fixture, team)` marker (`dossier_update` table) so a recap is folded exactly once.
- **Odds polling stays SEPARATE.** It's a global, quota-limited external poll (The Odds API,
  500/mo) with a different cadence — a second, less-frequent `ingest odds` timer. The tick consumes
  whatever odds exist and simply waits to bet a fixture until its odds are present (never blocks).
- **Windows are tunable** (`config.py`, hours relative to kickoff): `BRIEF_LEAD_HOURS=24`,
  `BET_LEAD_HOURS=3`, `RESULT_DELAY_HOURS=2.5`.

## 2. Design

- **`config.py`:** the three window constants.
- **`db.py`:** `dossier_update(fixture_id, team_id, at)` marker table + `dossier_folded` /
  `mark_dossier_folded`.
- **`orchestrate.py` (NEW):**
  - Pure-ish due-list selectors: `due_for_result`, `due_for_settle`, `due_for_postprocess`,
    `due_matchdays`, `due_for_brief`, `due_for_bet` (deterministic given `now` + DB state →
    unit-testable offline).
  - `_postprocess(conn, fixture, now)` — per-team recap (`build_post_match_report`, idempotent) +
    guarded dossier fold (`update_dossier_after_match` + marker).
  - `tick(conn, *, now=None) -> dict` — runs the six phases in order, each item wrapped in
    try/except, returns a counts+errors summary.
  - CLI: `orchestrate tick` (act) and `orchestrate status` (read-only: what's due now, no actions).

## 3. Acceptance criteria

1. Each due-list selector picks exactly the right fixtures at a controlled `now` (brief window, bet
   window incl. briefing+odds gating, result delay, settle-when-unsettled, postprocess-when-unfolded).
2. `due_matchdays` returns only fully-closed, not-yet-decayed days.
3. `tick` on an all-future DB is a **no-op**: zero actions, **zero `model_call` rows**, no errors
   (offline-safe — proves nothing fires before its window).
4. Dossier fold marker: `dossier_folded` flips after `mark_dossier_folded`; a folded `(fixture,
   team)` is excluded from `due_for_postprocess`.
5. A failing per-fixture action is caught, recorded in `summary["errors"]`, and does not abort the tick.
6. Ordering: results/settle/post-match happen before brief before predict/bet (by construction; asserted via a no-op + code structure).
7. `ruff` + `black` clean; all prior regressions still pass.

## 4. Verification
`scripts/verify_orchestrate.py` — synthetic, offline: build fixtures at controlled kickoff offsets
from a fixed `now`, assert every selector + the marker + the all-future no-op (asserting no
`model_call` rows). Live: `orchestrate status` + `orchestrate tick` on a seeded DB whose only
fixture is the future opener → "nothing due" / all-zero summary with no network calls.

## 5. Deployment (systemd, two timers) — notes
```
# orchestrate.timer  -> every ~20 min: ExecStart=uv run python -m worldcup_agents.orchestrate tick
# odds.timer         -> every ~6 h:   ExecStart=uv run python -m worldcup_agents.ingest odds
```
Both idempotent; the tick is the brain, the odds timer just keeps the market fresh under quota.

## 6. Open follow-up (not this slice)
`predict.run_fixture` doesn't skip eliminated competitors (`active=False`) — pre-existing, orthogonal
to orchestration. Log it; address with the betting mechanic later.

## 7. Results (2026-06-06 — COMPLETE)
- **Files touched:**
  - `config.py` — `BRIEF_LEAD_HOURS=24`, `BET_LEAD_HOURS=3`, `RESULT_DELAY_HOURS=2.5`.
  - `db.py` — `dossier_update` marker table + `dossier_folded` / `mark_dossier_folded`.
  - `orchestrate.py` (NEW) — the six due-list selectors, `_postprocess` (per-team recap + guarded
    dossier fold), `tick(conn, *, now)` (six phases in temporal-integrity order, per-item
    try/except, returns a counts+errors summary), and CLI `tick` / `status`.
  - `scripts/verify_orchestrate.py` (NEW) — offline regression for the selectors, the marker, and
    the idle-tick no-op.
- **How verified:** `verify_orchestrate.py` PASS (every selector at a fixed `now`; settle/postprocess
  exclusion after action; decay only on fully-closed days; **idle tick = zero actions + zero
  `model_call` rows**). All prior suites (`settlement`, `scoring`, `results`) still PASS. Live CLI
  smoke: `orchestrate status` + `tick` on a DB whose only fixture is the future opener → nothing
  due, all-zero summary, 0 LLM calls (today 2026-06-06 < kickoff 2026-06-11). `ruff` + `black`
  clean (21 files).
- **Decisions:** odds polling kept as a SEPARATE timer (global, quota-limited) — the tick defers
  betting a fixture until its odds exist, never blocks. Dossier fold guarded per `(fixture, team)`
  (the one non-idempotent step). Per-fixture failures are caught so one bad match never aborts a tick.
- **Deploy:** two systemd timers (§5) — `orchestrate tick` ~every 20 min, `ingest odds` ~every 6 h.
- **Follow-up (logged, not this slice):** `predict.run_fixture` should skip eliminated
  (`active=False`) competitors — pre-existing, belongs with the betting mechanic.

The per-fixture pipeline is now end-to-end and driven: ingest → brief → predict/bet → result →
settle → decay → leaderboards, sequenced by an idempotent tick. The competition can run unattended.
