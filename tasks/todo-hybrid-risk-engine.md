# Hybrid risk engine (Phase 5)

Built on top of Codex's full-distribution provenance slice. The model OWNS the decision
(its revised 1X2 distribution, its requested pick, its requested stake); the engine is a
risk layer that validates the pick and sizes the stake — it never substitutes a pick.

## Decisions (set by the user; revised after Codex's review)

- EV gate: **≥ 1.5%** (`MIN_BET_EV = 0.015`). NOT bare positivity. Because the floor lifts any
  surviving bet to 2%, an EV>0 gate would turn probability-rounding noise into $20k bets; the
  1.5% gate means only a real edge bets, then gets floored. (Was EV>0 → revised per Codex #1/#2.)
- Stake ceiling: **flat half-Kelly at every stage** (`KELLY_FRACTION = 0.5`; full Kelly =
  EV/(odds-1)). NOT ramped — Kelly assumes calibrated probabilities, these are uncalibrated LLM
  numbers, and full Kelly on an over-confident final estimate could lose half the bankroll.
  (Was ramped ½→full → revised per Codex #3.)
- Per-match cap: **ramped by stage** — 25% (group) → 50% (final) (`STAGE_MAX_STAKE_FRACTION`).
  This now carries ALL the late-stage aggression: only a genuinely big edge bets bigger late.
- Aggregate exposure: **50%** of bankroll across unsettled matches (`MAX_AGGREGATE_EXPOSURE`),
  enforced in code (best-effort; read-then-write not atomic — safe under the sequential timer,
  see Codex #5).
- Minimum bet: **2%** when a model bets and the pick clears the EV gate (`MIN_STAKE_FRACTION`)
  — no trivial bets; the one rule that can RAISE a stake, bounded by cap/exposure, never lifts a
  gated noise edge.
- Pass policy (prompt): **bet a genuine edge, pass only on a true toss-up.** `SYSTEM_GAMBLER` +
  the bet prompt reward backing a real read while explicitly NOT treating a hair-thin gap as an
  edge.
- Human challenger: **flat 25% manual cap** (no Kelly, no exposure cap) — reverted from
  stage-aware caps so its rules, metadata, and provenance are consistent (Codex #4).

## Final stake formula

`final = clamp( min(requested, stage-Kelly, stage-cap, remaining-exposure), low=2% floor )`
— the floor and Kelly fraction and cap are all bounded so a bet never breaches cap/exposure;
a bet squeezed to zero becomes a pass. `engine_adjustment` records the binding rule
(`kelly_cap` / `stake_cap` / `exposure_cap` / `min_floor` / `ev_guard`).

## What changed

- `config.py`: `MIN_BET_EV` → 0.0; added `STAGE_KELLY_FRACTION`, `STAGE_MAX_STAKE_FRACTION`,
  `MAX_AGGREGATE_EXPOSURE`, `MIN_STAKE_FRACTION`, and `stage_kelly_fraction()` /
  `stage_cap_fraction()` helpers. `MAX_STAKE_FRACTION` / `KELLY_FRACTION` kept as group defaults.
- `predict.py`: `_size_stake()` does the clamp+floor and labels the binding rule; `bet()` uses
  the stage-aware cap/Kelly; malformed distribution → one retry, then fail closed; bet prompt +
  `SYSTEM_GAMBLER` rewritten for the new pass policy and stage-aware cap display.
- `experiment.py`: phase `phase_5_hybrid_risk_engine`; bumped bet prompt + rules labels.
- `models.py`: documented `kelly_cap` / `exposure_cap` / `min_floor` in `engine_adjustment`.
- `web/challenger.py`: human per-match cap is now stage-aware too (parity); human still sizes
  manually (no Kelly, no floor).

## NOT changed / parked for later

- Calibration of the blind forecast, shadow strategies, decay redesign.

## Verification

- `scripts/verify_hybrid_risk_engine.py` — 10 offline checks (EV>0 sub-5% edge floored;
  mid stake unchanged; Kelly shrinks; floor lifts a trivial bet; group cap binds; exposure
  trims; exposure-full passes; stage ramp bets ~2x bigger in the final; retry recovers; retry
  fails closed). `scripts/verify_market_reconciliation.py` — Codex's 10, still green. Whole
  offline suite + repo-wide `ruff` clean.
- LIVE smoke (real OpenRouter, throwaway DB): 7/7 models emit valid distributions, 0 format
  failures; bet rate and sizing confirmed across efficient / coin-flip / value-present scenarios.

## NOT yet done

- Uncommitted; not deployed. Server still runs deployed Phase-2 code.
</content>
