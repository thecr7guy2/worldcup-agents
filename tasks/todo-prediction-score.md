# Slice: Scoreline prediction + weighted accuracy leaderboard

**Status:** IN PROGRESS. **Executor:** Opus.
**Read first:** DESIGN §2 (two-step agent), §6 (leaderboards). Prediction loop + scoring are done
(`tasks/todo-prediction.md`, `tasks/todo-scoring.md`). This enriches the PREDICT step only.

---

## 0. Scope & intent (from the user)

The two routes are asymmetric and stay that way:
- **PREDICT (mandatory)** — every model predicts every match.
- **BET (optional)** — only when confident; passing is legitimate. **UNCHANGED by this slice.**

Change: PREDICT now also emits a **scoreline** (predicted 90' home/away goals). The score is a
prediction-route artifact ONLY — it does **not** enter the bet prompt or the bet. The accuracy
leaderboard becomes **weighted**: correct outcome scores base points; a correct exact score scores
double (DESIGN §7 carry-through: exact score is judged on the 90-minute score).

## 1. Design

- **Derive the winner FROM the score.** The model emits `home_goals`/`away_goals`; `winner` is
  computed (`>`/`<`/`=`). One source of truth → no winner-vs-score contradiction. `confidence`
  (outcome-level, bridges into the stake) and `reasoning` stay.
- **`models.py`:** `Prediction` gains `pred_home_goals: int | None`, `pred_away_goals: int | None`
  (nullable so legacy rows still load). `winner` stays a stored field (set from the score).
- **`db.py`:** add the two columns to the `prediction` schema AND an idempotent
  `ALTER TABLE ... ADD COLUMN` migration in `init_db` (live DB already has the table). Round-trip
  the new fields in `upsert_prediction` / `get_prediction` / `list_predictions`.
- **`predict.py`:** Step-1 prompt asks for `{home_goals, away_goals, confidence, reasoning}`;
  parse ints (non-negative), derive `winner`, persist the score. BET step prompt untouched. CLI
  table + `format_reasoning` show the predicted score.
- **`config.py`:** `POINTS_CORRECT_OUTCOME = 1`, `POINTS_CORRECT_SCORE = 2` (exact doubles; tunable).
- **`leaderboard.py`:** `accuracy_standings` returns `{model, points, exact, outcomes, total,
  hit_rate}`; points = exact→`POINTS_CORRECT_SCORE`, else outcome→`POINTS_CORRECT_OUTCOME`, else 0.
  Exact ⟺ `pred_home_goals == home_goals_90 and pred_away_goals == away_goals_90`. Order by points,
  then exact, then outcomes. `hit_rate = outcomes / total`. Print shows points + the breakdown.

## 2. Acceptance criteria

1. PREDICT persists `pred_home_goals`/`pred_away_goals`; `winner` equals the score's outcome.
2. Invalid/missing/negative goals → `LLMError` (fail loud, no silent default).
3. BET prompt + `Bet` are byte-for-byte unaffected (score never appears there).
4. Accuracy points: exact score → 2; correct outcome only → 1; wrong outcome → 0.
5. §7: predicted 2-1 home in a 1-1 (pens) match → 0; predicted 1-1 → exact (2, draw outcome).
6. Predictions on unfinished fixtures excluded; board ordered by points desc.
7. `init_db` migrates an existing column-less `prediction` table without data loss; idempotent.
8. `ruff check` + `black --check` clean; existing settlement/scoring regressions still pass.

## 3. Verification
Extend `scripts/verify_scoring.py` (accuracy section) for the weighted points + exact-score cases
and the §7 carry-through; add a migration check (open a DB with an old-shape `prediction` table →
`init_db` adds the columns, existing rows survive). CLI smoke `predict`/`leaderboard` rendering.

## 4. Results (2026-06-06 — COMPLETE)
- **Files touched:**
  - `config.py` — `POINTS_CORRECT_OUTCOME = 1`, `POINTS_CORRECT_SCORE = 2`.
  - `models.py` — `Prediction.pred_home_goals/pred_away_goals` (nullable) + `has_score` property.
  - `db.py` — `prediction` schema gains the two columns; `init_db` runs an idempotent
    `ALTER TABLE ADD COLUMN` migration (`_migrate_schema`/`_add_column_if_missing`) so an existing
    column-less table is upgraded without data loss; round-trips updated in
    `upsert_prediction`/`get_prediction`/`list_predictions`.
  - `predict.py` — Step-1 prompt asks for `{home_goals, away_goals, confidence, reasoning}`;
    parses non-negative ints, **derives `winner` from the score**, persists it. BET step untouched.
    CLI table + `format_reasoning` show the predicted scoreline.
  - `leaderboard.py` — `accuracy_standings` now weighted: exact 90' score → 2, correct outcome →
    1, else 0; returns `{model, points, exact, outcomes, total, hit_rate}` ordered by points.
  - `scripts/verify_scoring.py` — accuracy section rewritten for the weighted scoring + a
    migration check.
- **How verified:** `scripts/verify_scoring.py` and `scripts/verify_settlement.py` both PASS
  (weighted points incl. the §7 1-1-pens prediction scoring 0; unfinished fixtures excluded;
  old-shape `prediction` table migrated, row preserved). CLI smoke of the accuracy board: exact
  2-1 → 2pts, right-result/wrong-score → 1pt, wrong → 0. `ruff` + `black --check` clean (17 files).
- **Decisions:** winner is derived from the score (one source of truth, no contradiction); the
  score is prediction-route only and never enters the BET prompt/`Bet`; point values live in
  `config.py` (a goal-difference tier could be added later if desired).
- **Next:** result ingestion (web/API → replaces manual `result`) + the orchestrator tick
  (settle → decay → brief → predict/bet).
