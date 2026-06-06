# Slice: Scoring — idle-cash decay + the two leaderboards

**Status:** IN PROGRESS. **Executor:** Opus.
**Read first:** DESIGN §5 (passing & idle decay), §6 (two leaderboards). Settlement is done —
see `tasks/todo-settlement.md`. This is its named "next slice" (minus result ingestion, which is
the separate automation slice).

---

## 0. Scope

- **IN:** (1) **idle-cash decay** — per matchday, un-staked bankroll bleeds `IDLE_DECAY` (0.5%),
  the anti-cowardice guardrail that stops a pure-passer winning by doing nothing. (2) the **two
  leaderboards** — Bankroll (primary) and Accuracy points (secondary, stakes ignored).
- **OUT:** real result ingestion (web/API — replaces manual `result`, belongs to the orchestrator
  slice); the orchestrator tick itself; ROI/Sharpe-style richer stats.

## 1. Load-bearing rules

- **Decay hits only the un-staked portion** (DESIGN §5). Per matchday: `idle = max(0, bankroll −
  staked_that_matchday)`, `delta = −IDLE_DECAY × idle`. A competitor who bets nothing bleeds the
  full 0.5%; one who risks capital bleeds proportionally less. Skipping one matchday is negligible;
  passing ~all of them slides you below $1M — exactly the intent.
- **Matchday = UTC calendar date** of kickoff (our fixtures carry kickoff, not the openfootball
  matchday label). Tunable proxy; matches intuition.
- **Decay runs at matchday CLOSE.** Guard: refuse a matchday with any fixture not yet
  FINISHED/POSTPONED — decaying before bets are placed would lock in an overstated idle base.
- **Decay does not bust/eliminate.** It's a bleed, not a betting loss; at 0.5%/day it can't reach
  the $10k floor within the tournament. Eliminated (inactive) competitors are skipped (frozen).
- **Idempotent** via a `matchday_decay` marker table (PK = matchday); atomic apply (competitor
  updates + ledger entries + marker in one commit). Ledger reason = `idle_decay`, `fixture_id` NULL.
- **Accuracy uses the PREDICTION, not the bet** (DESIGN §6: "raw correctness, stakes ignored").
  Correct ⟺ `prediction.winner == fixture.result_90()`, counted only over FINISHED fixtures with a
  known 90' result. Bankroll board already lives in `competitor` (ordered desc).

## 2. Design

### `settlement.py` (+ decay — it's a bankroll mutation, lives with settle)
- `apply_idle_decay(conn, matchday: str) -> list[BankrollEntry]` — idempotent (skip if marked),
  close-guarded, atomic. Computes staked-per-model for the matchday, bleeds the idle remainder of
  each active competitor, logs `idle_decay` ledger entries, writes the marker.
- CLI: `decay <YYYY-MM-DD>` — apply + print the per-model bleed.

### `leaderboard.py` (NEW — read-only presentation)
- `bankroll_standings(conn) -> list[Competitor]` (bankroll desc; rank in formatting).
- `accuracy_standings(conn) -> list[dict]` — `{model, correct, total, hit_rate}`, ordered by
  correct then hit_rate; only fixtures with a known result count.
- CLI: `python -m worldcup_agents.leaderboard [both|bankroll|accuracy]` (default both).

### `db.py` helpers
- `staked_by_model_on(conn, matchday) -> dict[str, float]` (SUM(stake) JOIN fixture on `date(kickoff)`).
- `matchday_decayed(conn, matchday) -> bool`; `record_idle_decay(conn, matchday, comps, entries)` (atomic).
- `fixtures_on_date(conn, matchday) -> list[Fixture]` (for the close-guard).
- `list_predictions(conn) -> list[Prediction]` (all, for the accuracy tally).
- SCHEMA: `matchday_decay(matchday TEXT PRIMARY KEY, applied_at TEXT)` (additive, `IF NOT EXISTS`).

## 3. Acceptance criteria

1. Pure passer: after `decay`, `bankroll == start × (1 − IDLE_DECAY)`; one `idle_decay` ledger row
   (fixture_id NULL); no bust/elimination.
2. Partial bettor: `delta == −IDLE_DECAY × (bankroll − staked)`; a full-risk edge (idle ≤ 0) → delta 0.
3. Eliminated competitor (active=0) is skipped (bankroll unchanged, no ledger row).
4. Idempotent: re-running `decay` for the same matchday changes nothing (marker guard).
5. Close-guard: `decay` on a matchday with an unfinished fixture raises a clear error.
6. Accuracy board: correct ⟺ `winner == result_90`; predictions on unfinished fixtures excluded;
   the §7 case (1-1 pens, predicted home) counts as WRONG (draw on 90').
7. Bankroll board ordered by bankroll desc with correct ranks.
8. `ruff check` + `black --check` clean.

## 4. Verification

`scripts/verify_scoring.py` — synthetic, self-contained (temp DB, no LLM/network): seed competitors
+ fixtures + predictions/bets, finish the matchday, assert every AC incl. idempotent decay and the
accuracy §7 case. Plus a CLI smoke of `decay` and `leaderboard`.

## 5. Working notes / decisions
- Decay base = post-settlement bankroll at matchday close; orchestrator order will be settle →
  decay. Matchday granularity (UTC date) and 0.5% are tunable in `config.py`.

## 6. Results (2026-06-06 — COMPLETE)
- **Files touched:**
  - `src/worldcup_agents/settlement.py` — added `apply_idle_decay` (idempotent, close-guarded,
    atomic; bleeds only the un-staked remainder; never busts) + a `decay <YYYY-MM-DD>` CLI command.
  - `src/worldcup_agents/leaderboard.py` (NEW) — `bankroll_standings`, `accuracy_standings`
    (grades the prediction vs `result_90` over finished fixtures only) + a CLI printing both boards.
  - `src/worldcup_agents/db.py` — `matchday_decay` table; helpers `fixtures_on_date`,
    `staked_by_model_on`, `matchday_decayed`, `record_idle_decay` (atomic), `list_predictions`.
  - `scripts/verify_scoring.py` (NEW) — self-contained synthetic regression for every AC.
- **How verified:** `uv run python scripts/verify_scoring.py` → all ACs PASS (passer bleeds the
  full 0.5%; partial bettor bleeds only `0.5% × (bankroll − staked)`; a no-idle competitor and an
  eliminated one are untouched; close-guard raises on an unplayed matchday; decay is idempotent;
  accuracy grades `winner == result_90`, excludes unfinished fixtures, and counts the 1-1-on-pens
  prediction as WRONG; bankroll board ordered desc). CLI smoke-tested: `decay 2026-06-11` (GPT-5.5
  staked $150k of its $1.066M → idle $916k → −$4,580 bleed; passers −$5,000), idempotent re-run is
  a no-op, `leaderboard` prints both boards. `ruff check` + `black --check` clean (17 files).
- **Decisions confirmed:** matchday = UTC kickoff date; decay base = post-settlement bankroll at
  matchday close (orchestrator order will be settle → decay); decay is a pure bleed (no bust).
- **Follow-ups (next):** result ingestion (web/API, replaces manual `result`) + the orchestrator
  tick that sequences settle → decay → brief → predict/bet. Optional: seed an `init` ledger row at
  competitor creation so the bankroll ledger sums from $1M.
