# Slice: report-instrumentation features (2026-06-10, day before kickoff)

Goal: features that materially improve the technical report, shipped BEFORE the first
prediction locks (anything touching prompts or capture is frozen after match 1 for
comparability). Approved direction: richer reasoning (4-8 sentences) + new report value.

## Checklist

- [x] **Reasoning length** — predict `2-4` → `4-8 sentences` (walk through the weighing);
      bet `1-3` → `2-5 sentences` (where the value is + why this stake size).
- [x] **`prediction.key_factors`** — 3-6 short lowercase tags per forecast (lenient parse,
      `_parse_key_factors`: dedup, ≤8 tags, garbage → None, never fails a forecast).
      Additive column; round-trips through upsert/get/list.
- [x] **Input-side audit capture** — `model_call.prompt_text` (exact prompt sent) and
      `model_call.annotations_json` (web-search citations). Completes the verbatim trail
      started with response_text/reasoning_text.
- [x] **Tournament outlook interviews** — new `outlook.py` + `tournament_outlook` table.
      Phases: pre / post_group / pre_final / post_final. Idempotent per (model, phase);
      per-model failures collected, not fatal. Run `pre` TODAY (before any group result).
      Never fed back into the pipeline.
- [x] **Near-kickoff odds refresh** — `ingest.poll_odds()` extracted from `cmd_odds`;
      tick step 7.5 polls once when any fixture in the late-update horizon has missing or
      >45-min-old consensus odds (`ODDS_REFRESH_MAX_AGE_MIN`). Fresh line at bet time +
      true closing-line metric + self-heals missed events. Quota: ~1-2 extra credits per
      kickoff slot on top of ~120/mo baseline — well inside 500/mo.
- [x] DESIGN.md §12 documents the measurement layer.
- [x] Verify (below).
- [ ] Run `outlook ask --phase pre` on the server before kickoff. Re-ask at `post_group`
      (after 2026-06-27) and `pre_final` / `post_final`.

## Acceptance criteria

- New prompt fields parse leniently; a model omitting them still produces a valid forecast.
- Old DBs migrate additively; existing rows untouched.
- Outlook ask is idempotent per phase and survives a single model failing.
- The odds-refresh selector is deterministic and offline-testable; a failed poll never
  blocks betting.

## Results / verification story

- `.cache/verify_features.py` (throwaway DBs, mocked httpx/complete): 26/26 — includes an
  end-to-end `predict()` through the NEW prompt asserting the prompt text and stored tags.
- `uv run ruff check src scripts` — clean.
- `scripts/verify_{results,orchestrate,settlement,scoring,bracket}.py` — ALL PASS.

## Post-hoc roadmap (no deadline pressure; build mid-group-stage)

- `report.py`: Brier/log-loss + calibration curves (incl. de-vigged market as benchmark
  forecaster), CLV vs closing snapshot, Kelly-shadow counterfactual bankrolls (decomposes
  bankroll into forecasting vs staking skill), baselines (always-favorite / passer /
  random), bootstrap CIs on leaderboard gaps, disagreement matrix, factor-attribution and
  tilt analysis.
- Exit interviews at elimination (outlook mechanism, new phase) — optional.
- Self-consistency probe (re-sample a few fixtures' forecasts as shadow calls,
  step="probe") — optional, costs real credits; decide later.
