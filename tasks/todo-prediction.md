# Slice: Gambler loop — Step 1 PREDICT + Step 2 BET (the 5 competitors)

**Status:** IN PROGRESS. **Executor:** Opus.
**Read first:** DESIGN §2 (two-step agent), §5 (gambler model), §6 (leaderboards). Intelligence
layer (briefings + post-match) is done — see `tasks/todo-intelligence.md`.

## 0. Scope
- **IN:** for one fixture, run all 5 PREDICTION_MODELS through the two steps and persist:
  - Step 1 PREDICT (odds HIDDEN): briefing → `{winner, confidence, reasoning}` → `prediction` table.
  - Step 2 BET (odds SHOWN + bankroll + 25% cap): → `{pick, stake}` or pass → `bet` table.
- **OUT (next slice):** settlement, bankroll updates, idle decay, bust/re-buy, leaderboards.

## 1. Load-bearing rules
- **Identical system prompt for all 5** (mindset induction, DESIGN §5) — only the model differs.
- **Odds hidden in Step 1** — prediction is pure football judgment. Odds injected only at Step 2.
- **Confidence (0-1) from Step 1 bridges into the stake** — it is NOT a score, just informs sizing.
- **25% per-match stake cap** (`MAX_STAKE_FRACTION`); passing (stake 0) is legitimate.
- Settlement is on the 90-minute 1X2 result (winner only) — no exact score.

## 2. Design
- New module `predict.py`:
  - `SYSTEM_GAMBLER` — shared mindset prompt.
  - `predict(model, fixture, briefing) -> Prediction` (JSON out: winner/confidence/reasoning).
  - `bet(model, fixture, prediction, odds, bankroll) -> Bet` (JSON out: pick/stake/reasoning; cap-clamped).
  - `run_fixture(conn, fixture_id) -> list[(Prediction, Bet)]` — all 5 models, idempotent/lazy.
  - argparse CLI: `predict <fixture_id>`.
- Structured output via strict JSON + tolerant `_parse_json` (extract first {...}); validate enums.
- `db.py`: `upsert_prediction`/`get_prediction`, `upsert_bet`/`get_bet`, `list_predictions(fixture)`,
  `consensus_odds(fixture)` (the bookmaker="consensus" snapshot).

## 3. Acceptance criteria
1. `predict <fixture_id>` writes 5 predictions + 5 bets for the opener.
2. Each prediction has winner ∈ {home,draw,away}, confidence ∈ [0,1], non-empty reasoning.
3. Step-1 prompt contains NO odds (assert the briefing text has none; guard).
4. Each bet stake ≤ 25% of that model's bankroll; pick ∈ {home,draw,away} or pass(stake 0).
5. `bet.odds_at_bet` matches the consensus odds for the pick.
6. Idempotent re-run (no dup rows, no new LLM calls).
7. Every call logged to `model_call` (steps `predict`, `bet`). `ruff`/`black` clean.

## 4. Results (2026-06-05 — Step 1 + Step 2 COMPLETE)
- **Files:** `predict.py` (NEW — `SYSTEM_GAMBLER`, `predict`, `bet`, `run_fixture`, `_extract_json`,
  CLI); `db.py` (+`get_competitor`, `upsert/get_prediction`, `upsert/get_bet`, `consensus_odds`).
- **Verified on opener (103, Mexico vs South Africa, consensus 1.44 / 4.43 / 8.55):** all 5 models
  predicted home (conf 0.65–0.75); GPT-5.5 & MiniMax PASSED (no value at 1.44), Sonnet $150k / Kimi
  $120k / DeepSeek $180k backed it — stakes scale with conviction, all ≤ 25% cap ($250k). All ACs
  pass; idempotent re-run (0 new calls); `model_call` logged predict×5 + bet×5; ruff/black clean.
- **Gotcha logged:** Kimi-K2.6 is a reasoning model — `max_tokens=1200` was consumed entirely by
  reasoning tokens (`finish_reason=length`, empty content). Raised predict/bet budget to 4000.
- **Next slice:** settlement → bankroll/idle-decay/bust-rebuy → the two leaderboards. Needs a
  90-min result; can be built now and tested with a synthetic result on the opener.
