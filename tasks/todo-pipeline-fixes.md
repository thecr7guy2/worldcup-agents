# Slice: Pre-kickoff prediction-pipeline corrections (#1–#6)

**Status:** PLANNED — awaiting go-ahead.
**Deadline:** must land + dry-run before **2026-06-11** kickoff.
**Read first:** `tasks/DESIGN.md` (source of truth) and the load-bearing invariants in
`CLAUDE.md`. This slice changes prompts, the prediction schema, orchestration timing, and
intelligence research — all on a system that goes live in days and must stay comparable
across all 104 matches once it starts.

## 0. Why this slice exists

A review of the live pipeline found the architecture sound (shared briefing, odds hidden in
Step 1, temporal integrity, 90' settlement) but surfaced information-quality and
calibration problems. Scope chosen by the user: **#1–#6** (defer #7 structured-KB redesign
and #8 calibration scoring / Kelly / paid feeds / backtest — multi-week, post-kickoff).

## 1. Invariants this slice must NOT break

- Shared knowledge base, never shared judgment (one briefing, all models read it).
- No odds in the briefing / Step 1. Odds only enter Step 2.
- Neutral briefings (facts, no lean).
- Temporal integrity: nothing after a fixture's cutoff enters that fixture's briefing.
- 1X2 settles on the 90' score; `advanced_id` records progression.

## 2. The slices (each its own commit, in order)

### Slice 1 — Neutral forecaster vs gambler prompt  (#1, `predict.py`)
Root cause: `SYSTEM_GAMBLER` (predict.py:36-54) is shared by BOTH steps, so the Step-1
prediction inherits "favorites are routinely overrated / biggest payouts from upsets."
- Add `SYSTEM_FORECASTER` (Step 1): neutral analyst seeking the most *accurate* 90'
  probabilities; no betting framing, no upset-seeking, no side preference.
- Keep `SYSTEM_GAMBLER` for Step 2 only; soften "favorites overrated/upsets" to neutral
  "look for mispriced lines in either direction."
- `predict()` uses forecaster; `bet()` uses gambler.
- Risk: low (prompt-only). 

### Slice 2 — Name the opponent  (#2, `intelligence.py`)
`build_pre_match_report` (intelligence.py:219) never names the opponent, so "Tactics &
matchup" is opponent-blind. Pass `opp` into the report and reference it explicitly. The
team dossier (team-only, reused across fixtures) stays opponent-agnostic — only the
fixture-specific pre-match report names the opponent. Risk: tiny.

### Slice 3 — Deeper research  (#3, `intelligence.py` + `llm.py`)
One `web_search` at `max_results=5` (llm.py:71) covers 6 topics. Raise intelligence-call
`web_max_results` to ~12 (config-driven) and instruct the model to prioritise CONFIRMED
availability with sources. Stretch: split the pre-match report into two focused searches
(availability/lineups + form/tactics/conditions). Risk: low (more tokens/cost).

### Slice 4 — Full 1X2 probability distribution  (#4 — schema change)
`predict.py:91-106` asks for one scoreline and derives the winner; the most-likely score
(1-1) can disagree with the most-likely outcome. Move to an explicit distribution.
- `models.Prediction`: add `p_home,p_draw,p_away,exp_home_goals,exp_away_goals` (float|None).
  `winner` now derived from `argmax(p_*)`; `pred_home/away_goals` = most-likely score (for the
  exact-score accuracy point); `confidence = p[winner]` (now genuinely a probability).
- `db.py`: additive `ALTER TABLE prediction ADD COLUMN ...` via the existing init_db migration
  helper (db.py:208-210); update `upsert_prediction`/`get_prediction`/`list_predictions`.
- `predict.predict()`: prompt requests `{p_home,p_draw,p_away,expected_home_goals,
  expected_away_goals,most_likely_score,(advances),reasoning}`; normalise probs to sum 1,
  derive winner, parse score, set confidence.
- `predict.bet()`: show the model its own distribution next to odds (proper edge calc) —
  addresses the "confidence not calibrated / contradictory bets" finding.
- `web/stats.py` fixture_detail + `web/lib/api.ts` BoardEntry: surface `p_*`; minimal
  probability display on the fixture-detail board.
- Settlement/accuracy UNCHANGED (winner is still an `Outcome`; exact-score still from goals).
- Risk: medium; migration safe (0 predictions in live DB yet, columns nullable).

### Slice 5 — Late lineup/weather delta  (#5 — orchestration)
Briefing at T-24h, predictions at T-3h (config.py:82-84); confirmed XIs arrive near KO.
- `config.BET_LEAD_HOURS` 3.0 → 1.5 (predictions lock ~T-90..60m given 30-min ticks).
  Documented tradeoff: less compute margin on busy matchdays (mitigate with 15-min tick).
- `models.LateUpdate(fixture_id,cutoff_at,content)`; `db` `late_update` table + upsert/get.
- `intelligence.build_late_update(fixture, *, cutoff)`: ONE focused web search (confirmed XI,
  injuries, suspensions, late news, matchday weather); temporal guard `kickoff>cutoff`;
  stored (idempotent). NO odds. Neutral.
- `orchestrate.tick` step 7: best-effort `build_late_update` BEFORE `predict.run_fixture`
  (own try/except so a failed delta never blocks predictions).
- `predict.run_fixture`: append the late update to the briefing text passed into `predict()`
  (base briefing stays immutable; concat at predict time). Risk: medium (timing).

### Slice 6 — Dedup post-match research  (#6, `intelligence.py` + `orchestrate.py`)
`orchestrate._postprocess` (orchestrate.py:163-172) searches the same finished match once
per team. Add `intelligence.build_match_recap(fixture)`: ONE web search + ONE completion
returning both teams' recaps; persist each as `PostMatchReport`; fold each into its dossier
(guarded as today). Affects N+1 briefings only. Risk: low-med.

## 3. Acceptance criteria

1. Step 1 uses a neutral forecaster system prompt with no upset/value framing; Step 2 keeps
   the gambler prompt. (#1)
2. Pre-match reports name the opponent. (#2)
3. Intelligence web searches request >5 results and ask for sourced availability. (#3)
4. A prediction stores a normalised `p_home/p_draw/p_away`; `winner = argmax`; the live DB
   migrates additively with existing data intact; the frontend builds and shows probabilities. (#4)
5. A late-update report is built and folded into the briefing before predictions, with a
   cutoff < kickoff; `BET_LEAD_HOURS` reduced. (#5)
6. One web search per finished match produces both teams' recaps. (#6)
7. `scripts/dry_run.py` (full) is green: every competitor returns a valid distribution + bet,
   opponent named in the briefing, late update present. `cd web && npm run build` passes.
   `ruff` clean. No change to settlement/accuracy results on a replayed fixture.

## 4. Verification

- Per slice: targeted `uv run python -c` checks (pattern from prior slices) + `ruff check`.
- Schema: run `init_db` on a COPY of `worldcup.db`; assert new columns exist, old rows intact.
- Integration: `uv run python scripts/dry_run.py --models 1` then full — spends real
  OpenRouter credit; the real gate for the LLM path.
- Frontend: `cd web && npm run build`.
- Deploy (server): `git pull && uv sync && (cd web && npm ci && npm run build) &&
  sudo systemctl restart wc-api wc-web`; tick picks up new code next fire.

## 5. Rollback

All behind git; pre-kickoff so no feature flag needed. Revert the offending commit +
redeploy. Added columns are nullable/additive — safe to leave even after a code revert.

## 6. Results (landed 2026-06-07)

All six slices implemented + verified, plus one bug the dry-run gate caught.

- **#1** `predict.py`: split `SYSTEM_GAMBLER` → neutral `SYSTEM_FORECASTER` (Step 1) +
  value-seeking `SYSTEM_GAMBLER` (Step 2); upset rhetoric removed.
- **#2** `intelligence.py`: `build_pre_match_report` takes `opponent`; reports name the
  opponent in the matchup section.
- **#3** `config.INTEL_WEB_MAX_RESULTS=12` applied to all 4 intelligence web searches;
  Availability bullet now demands sourced/confirmed claims.
- **#4** 1X2 distribution: `Prediction` gains `p_home/p_draw/p_away/exp_*_goals`;
  `winner=argmax`, `confidence=p[winner]`, most-likely score kept for the exact-score
  point; additive DB migration; bet step shows distribution vs market-implied odds;
  surfaced in `web/stats.py` + `api.ts` + the fixture board.
- **#5** late update: `BET_LEAD_HOURS 3→1.5`; `LateUpdate` model + `late_update` table +
  `build_late_update` (focused web search, temporal-guarded); orchestrator builds it
  best-effort before predicting; appended to the briefing in `run_fixture`.
- **#6** `build_match_recap`: one web search → both teams' recaps; `_postprocess` folds
  each into its dossier (removed `_match_label` + the per-team double search).
- **Bug found by the gate:** intelligence calls were capped at `max_tokens=3000-4000`; the
  reasoning model spent the whole budget on hidden reasoning and returned empty content,
  failing the briefing. Added `config.INTEL_MAX_TOKENS=20000` for all intelligence calls.

**Verification:** `ruff` clean; additive migration tested on a copy of `worldcup.db`
(new columns present, 0 data loss, round-trips); `dry_run.py` cheap (1) and **full (7/7)**
green — every model returns a calibrated distribution + value bet, favorite correctly
favored (no upset bias), opponent named, late update built + used. Frontend
`npm run build` to be confirmed on the server at deploy (no Node on the Mac).

**Still open (deferred, post-kickoff):** #7 structured KB, #8 calibration/Brier
leaderboards + Kelly + paid feeds + backtest.

## 7. Review hardening (rounds 2 & 3, 2026-06-07)

Two further adversarial review passes before deploy; all verified by unit checks + a green
7/7 dry-run.

Round 2:
- Late update split into its OWN window (`due_for_late_update` ~T-75) ahead of predictions.
- Accuracy scoring decoupled: outcome graded off `winner`, never inferred from an exact score.
- `run_fixture` runs models with bounded concurrency (per-thread connections + busy_timeout)
  and a pre-call kickoff check; tick cadence dropped to 15 min.
- Bet prompt shows no-vig fair probabilities; `_prob` rejects NaN/inf.
- `build_match_recap` fails CLOSED on missing markers (no dossier pollution).

Round 3:
- Bet decision uses EV vs the OFFERED odds (break-even 1/odds); bets that are -EV by the
  model's own probabilities are overridden to a pass (`MIN_BET_EV`).
- Late update refreshes if stale at predict time (`LATE_UPDATE_REFRESH_MIN`).
- Kickoff re-checked inside `predict()`/`bet()` before every DB write (`KickoffPassed`).
- `run_fixture` returns per-model `ModelRun` statuses; the tick reports partial fixtures
  instead of counting them done.
- Knockout `advances` always requested separately (never derived from the 90' winner).
- Stake validation: finite + non-negative in parsing AND on `Bet.stake`.
- Eliminated competitors still predict (accuracy) but bets are forced to pass.
- Exact-score points require the outcome to also be correct.
