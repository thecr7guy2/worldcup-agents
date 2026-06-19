# Coherent tier betting (Phase 6)

This file keeps its historical name because deployment notes and verification commands link
to it. Phase 6 supersedes the Phase-5 EV/Kelly risk engine.

## Decisions

- Step 1 remains an odds-hidden 1X2 probability distribution.
- A Step-2 outcome is eligible when `p(top) - p(outcome) <= 0.10`.
- Odds may choose among eligible outcomes. They may not unlock a clearly unlikely longshot.
- The model chooses a fixed stake tier or passes.
- Group tiers: 5%, 10%, 15%, 20%.
- Round of 32 / round of 16: add 25%.
- Quarterfinal onward: add 30%.
- Aggregate unsettled exposure remains capped at 50% of bankroll.
- Matchday portfolio targets add slate pressure: 15% in groups, 20% in R32/R16, 25% from QF
  onward; unallocated target budget loses 25% at matchday close.
- Passing is normal. The prompt no longer tells agents to bet every real lean.
- Revised probabilities, market blending, EV gates, Kelly sizing, and minimum floors are gone.
- Malformed Step-2 JSON gets one format-only retry; semantic rule violations are not retried.
- The human challenger keeps its separate flat 25% manual cap.

## Examples

- Scotland 53%, draw 26%, Haiti 21%: only Scotland is eligible. Haiti cannot be selected
  merely because its odds are large.
- Home 40%, draw 25%, away 35%: home and away are eligible. The agent may use the odds to
  choose either side and can stake the full stage tier.
- Home 40%, draw 30%, away 30%: all three outcomes sit exactly inside the inclusive window.

## Verification

- `scripts/verify_hybrid_risk_engine.py` checks eligibility boundaries, large fixed tiers,
  passes, invalid tiers, stage ceilings, exposure, provenance, and legacy forecasts.
- `scripts/verify_market_reconciliation.py` now verifies the Phase-6 prompt and persistence
  contract while retaining legacy-schema and human-challenger coverage.
