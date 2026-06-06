# Slice: Knockout "who advances" prediction + advance accuracy points

**Status:** IN PROGRESS. **Executor:** Opus.
**Read first:** DESIGN §6 (leaderboards), §7 (90' settlement). Builds on the scoreline-prediction
slice (`tasks/todo-prediction-score.md`) and result ingestion (`tasks/todo-result-ingestion.md`,
which already populates `Fixture.advanced_id`).

---

## 0. Decision (from the user)

Prediction and betting routes are now intentionally asymmetric:
- **PREDICT** — keeps the 90' scoreline for EVERY match (the draw stays predictable/scored — the
  "called the 1-1 draw" signal we care about) AND, **for knockouts only**, adds a separate
  **"who advances"** call (the final winner, counting ET/penalties).
- **BET** — UNCHANGED. Still seeds off the 90' winner and bets the 90' 1X2. No to-advance odds
  needed (we keep the `h2h` feed we already ingest).
- **SETTLEMENT** — UNCHANGED. Still 90'.

Augment, not replace: a knockout's final winner is never a draw, so we add the advancer ON TOP of
the 90' prediction rather than swapping it out.

## 1. Design

- **`config.py`:** `POINTS_CORRECT_ADVANCE = 1` (knockout only; independent, stacks on the 90'
  points). Max knockout = exact score (2) + advance (1) = 3; max group = 2.
- **`models.py`:** `Prediction.predicted_advance: Outcome | None` (HOME/AWAY only; None for groups).
- **`db.py`:** `prediction.predicted_advance TEXT` column + idempotent migration; round-trips.
- **`predict.py`:** for knockout fixtures, the Step-1 JSON also carries `"advances": "home"|"away"`.
  Derivation mirrors `results._resolve_advanced`: a decisive predicted 90' score → the advancer is
  the 90' winner (derived, model's field ignored); a predicted 90' DRAW → require the model's
  `advances` (this is where the call actually matters). Group fixtures → `predicted_advance=None`.
  `--reasons` output shows the advancer for knockouts. BET prompt untouched.
- **`leaderboard.py`:** accuracy tally gains `advance`; +`POINTS_CORRECT_ADVANCE` when
  `predicted_advance` maps (HOME→home_id / AWAY→away_id) to `fixture.advanced_id`. Gated on
  `advanced_id is not None` (so only resolved knockouts), independent of the 90' outcome/score
  points. Display adds an `adv` column.

## 2. Acceptance criteria

1. Knockout predict persists `predicted_advance`; group predict leaves it None.
2. Decisive predicted 90' score → `predicted_advance` derived = 90' winner (model's field ignored).
3. Predicted 90' DRAW on a knockout with no/invalid `advances` → `LLMError` (the call is required
   exactly when it matters).
4. Accuracy: correct advancer on a resolved knockout → +1, INDEPENDENT of outcome/score points
   (e.g. predicted 1-1 + correct advancer on a 1-1-pens tie → 2 + 1 = 3; wrong 90' but right
   advancer → 0 + 1 = 1).
5. Group fixtures and unresolved knockouts (`advanced_id` None) score no advance points.
6. Migration adds `predicted_advance` to an existing table without data loss; idempotent.
7. BET prompt/`Bet` and settlement unchanged; `ruff`/`black` clean; all prior regressions pass.

## 3. Verification
Extend `scripts/verify_scoring.py` (accuracy + migration) for advance points (correct/wrong, the
1-1-pens combo, group/unresolved exclusion) and the new column migration. Synthetic, no network.

## 4. Results (2026-06-06 — COMPLETE)
- **Files touched:**
  - `config.py` — `POINTS_CORRECT_ADVANCE = 1`.
  - `models.py` — `Prediction.predicted_advance: Outcome | None` (HOME/AWAY; None for groups).
  - `db.py` — `prediction.predicted_advance` column + idempotent migration; round-trips via a new
    `_row_to_prediction` helper.
  - `predict.py` — knockout Step-1 prompt also asks `"advances"`; derive it (decisive 90' → winner;
    predicted draw → require the model's call, else `LLMError`); `--reasons` shows the advancer.
    BET prompt untouched.
  - `leaderboard.py` — accuracy tally gains `advance`; +`POINTS_CORRECT_ADVANCE` when the predicted
    advancer matches `fixture.advanced_id` (gated on a resolved advancer), independent of the 90'
    points; new `adv` column.
  - `scripts/verify_scoring.py` — advance scoring cases (showcase, independence, group/unresolved
    gate) + migration column check.
- **How verified:** `verify_scoring.py` / `verify_results.py` / `verify_settlement.py` all PASS.
  CLI smoke on an R16 1-1-pens tie (Spain advanced): GPT called the draw + advancer → 3 pts;
  MiniMax wrong 90' but right advancer → 1 pt (independence); Opus 0. Migration adds the column
  without data loss. BET/settlement unchanged. `ruff` + `black --check` clean (19 files).
- **Decisions confirmed:** augment, not replace — 90' scoreline stays for every match (draws remain
  predictable/scored); advancer added on knockouts only; betting + settlement + odds untouched
  (no to-advance feed needed); advance points stack independently (max KO = 3, group = 2).
- **Next:** the orchestrator tick — `ingest (due) → settle → decay → post-match → brief →
  predict/bet` off kickoff times, on a systemd timer.
