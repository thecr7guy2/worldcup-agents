# Experiment provenance and market regression

## Problem

The competition changed its Step-2 market logic after fixtures 103-106. Before this
slice, the database did not identify which prompt, rules, requested model, code revision,
or odds snapshot produced a prediction or bet. That made a defensible technical report
depend on timestamps and reconstructed deployment history.

The Canada-Bosnia failure mode also existed only as a throwaway server script, so a future
prompt or validation change could silently reintroduce the same favorite/underdog bias.

## Implemented

- [x] Add nullable provenance fields to `prediction`:
      experiment phase, prompt version, requested model ID, OpenRouter generation ID,
      and Git revision.
- [x] Add the same fields to `bet`, plus betting-rules version and the composite-key
      identifiers of the exact odds snapshot used.
- [x] Populate provenance on automated predictions, automated bets/passes, eliminated
      competitor passes, and Human Challenger decisions.
- [x] Persist the normalized requested pick/stake separately from the final settlement
      action, with the deterministic engine adjustment reason. Legacy revised-probability
      fields remain nullable for historical phases.
- [x] Fail closed on a non-pass with missing/invalid `p_revised`; never reuse the
      systematically-flat blind distribution for Step-2 EV.
- [x] Require and persist a complete normalized post-market home/draw/away distribution;
      calculate EV for every outcome while validating only the model-owned requested pick.
- [x] Keep additive migration compatibility: old rows load with NULL provenance.
- [x] Add a permanent offline Canada-Bosnia market-reconciliation regression.

## What this fixes

- Report rows can be partitioned by an explicit experimental phase instead of inferred
  from deployment timestamps.
- A bet can be joined back to the exact consensus odds snapshot that informed it.
- Model requests can be audited through requested model ID + OpenRouter generation ID.
- Report results can be tied to the exact Git revision and prompt/rules labels.
- The original flat-forecast failure shape is now executable regression coverage.
- The report can measure how often the engine changed a model action, why it changed it,
  and the requested versus accepted stake.

## What this does not change

- Provenance and requested/final action persistence do not alter settlement mechanics.
- Phase 3 changed one guard behavior: unverifiable non-pass responses became explicit
  passes instead of falling back to the blind forecast. Phase 4 supersedes that response
  shape with a complete distribution.
- The exact unparsed response remains in `model_call.response_text`; the `bet.requested_*`
  fields are its normalized, queryable action.
- Provider/model resolution behind an OpenRouter generation ID remains a report-time
  lookup rather than an extra live API call.

## Phase boundary

- Phase 1: fixtures 103-106, whose legacy rows have NULL `experiment_phase`.
- Phase 2: rows labeled `phase_2_market_reconciliation` used revised probability with
  a blind-forecast fallback.
- Phase 3: rows labeled `phase_3_fail_closed_revised_probability` require a valid revised
  probability for every non-pass.
- Phase 4: rows labeled `phase_4_full_revised_distribution` require the complete revised
  1X2 distribution and retain it even when the model voluntarily passes.
- Phase 5: rows labeled `phase_5_hybrid_risk_engine`. Same full revised
  distribution + model-owned pick, but `MIN_BET_EV = 0`, one retry before fail-closed, and
  engine-enforced half-Kelly + 50% aggregate-exposure stake protection. See
  `todo-hybrid-risk-engine.md`. (Phases 3 and 4 were dev-only and never produced live rows.)
- Phase 6: rows labeled `phase_6_coherent_tier_betting`. The blind distribution defines a
  10-point outcome-eligibility window; Step 2 chooses a fixed tier or passes. Revised
  probabilities, EV gates, Kelly sizing, and minimum floors are not part of this phase.

Do not use `p_revised IS NOT NULL` as the phase boundary: a Phase-2 pass can legitimately
have no persisted revised probability.

## Verification

Run:

```bash
uv run python scripts/verify_market_reconciliation.py
```

It covers prediction provenance, the blind eligibility contract, fixed-tier persistence,
ineligible-pick rejection, voluntary passes, exact odds snapshot persistence, the human
challenger cap, and migration of legacy rows.
