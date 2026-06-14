# Step-2 market reconciliation (revised probability)

> **SUPERSEDED (Phase 6, 2026-06-14).** This is the historical record of the revised-
> probability experiment. Production Step 2 now uses blind-forecast eligibility plus fixed
> stake tiers; revised probabilities, EV gates, and Kelly sizing are removed. See
> `todo-hybrid-risk-engine.md` and DESIGN §2.

## Problem (observed after matchdays 1–3)

All seven agents predicted the favorite and bet the underdog on every fixture with a
clear favorite (103 Mexico–RSA, 105 Canada–BIH); only the near-even 104 (KOR–CZE) saw
favorite bets. Root cause is mechanical, not behavioral:

- Blind Step-1 distributions are systematically FLATTER than the market (~45/30/25
  regardless of matchup; market had Canada ~53% fair, models said 39–45%).
- The negative-EV guard judged bets at those blind numbers, so a short-priced favorite
  could NEVER be bet (p × odds < 1 by construction) while every underdog showed a
  phantom +15–35% "edge".
- Step 2 therefore had no real decision to make — the guard picked the bet, not the
  model, and all seven behaved identically.

## Fix (this slice)

- [x] Step-2 prompt: market framed as evidence; model must reconcile its blind forecast
      with the line and output `p_revised` (probability its pick wins, post-market).
- [x] Phase 2 EV guard runs on `p_revised` (historical fallback: Step-1 probability when
      missing/invalid).
- [x] `MIN_BET_EV` 0.0 → 0.05 (a bet needs a clear edge, not a rounding artifact).
- [x] Persist `p_revised` on `bet` (schema + additive migration + round-trip helpers +
      Pydantic model) — report can measure each model's market-update behaviour.
- [x] SYSTEM_GAMBLER: added "respect the market" principle.
- [x] Surface `p_revised` in CLI table + `--reasons` markdown.
- [x] DESIGN.md §2 updated (source of truth stays in sync).
- [x] Verify on server: migration on live DB copy, stubbed-LLM bet() round trip
      (favorite-bet now possible; phantom-edge dog auto-passed; fallback path).
- [x] Deploy to server (live repo), run migration on live DB.

## Invariants preserved

- Step 1 untouched: still blind, still the accuracy-board artifact.
- Shared briefing untouched; both system prompts remain identical across all 7 models.
- The change is additive: legacy bet rows load (`p_revised` NULL), human-challenger
  betting behavior is unaffected.

## Acceptance criteria

- A model that revises its pick's probability above break-even + 0.05 can now bet a
  short-priced favorite (impossible before).
- A bet whose revised probability fails the threshold is auto-passed with the EV note
  naming "revised probability" as the basis.
- Phase 2 only: a response with no/invalid `p_revised` used the old Step-1 fallback.
- Live DB migrates additively; existing rows and the web app keep working.

## Phase marker (for the tech report)

Fixtures 103-106 were decided under the old blind-EV regime — treat them as Phase 1
(shared-miscalibration mechanism). Phase-2 rows explicitly store
`experiment_phase = 'phase_2_market_reconciliation'`; use that field instead of a
deployment timestamp. Do not use non-NULL `p_revised` as the Phase-2 marker because a
pass can legitimately persist no selected revised probability. Later phases carry their
own explicit labels.

The prompt/rules labels, requested model ID, OpenRouter generation ID, Git revision, and
exact odds-snapshot identifiers are also persisted for new rows. See
`tasks/todo-experiment-provenance.md`.

## Phase 3 hardening

The Phase-2 fallback was intentionally removed after requested-vs-final audit fields
landed. A non-pass with missing or invalid `p_revised` now fails closed with
`engine_adjustment = missing_revised_probability | invalid_revised_probability`.
This historical Phase-3 rule prevented malformed output from re-entering the flat
blind-EV regime; Phase 4 supersedes it with full-distribution validation.

## Phase 4 full distribution

Step 2 now requires `p_home_revised`, `p_draw_revised`, and `p_away_revised`. Small
rounding differences are normalized; missing, non-finite, negative, or materially
mis-summed distributions fail closed. The engine calculates EV for all three outcomes
but validates only the model's requested pick, preserving model ownership of the bet.

## Results (2026-06-13)

- Deployed to the server repo; live DB backed up
  (`backups/worldcup-pre-p_revised-*.db`) and migrated additively — 30 legacy bet rows
  untouched, legacy round-trip verified.
- Stubbed-LLM verification (`/tmp/verify_market_update.py`, throwaway DB): all five
  paths pass — favorite bettable at a clearing revised prob; phantom dog edge
  auto-passed "by revised probability"; missing `p_revised` falls back to Step-1 with
  the "(no revised given)" tag; legacy +EV path stands; NaN `p_revised` rejected.
- `wc-tick`/`wc-odds` run via `uv run` per tick → new code is live for the next tick;
  `wc-api` still has pre-change code in memory (compatible — explicit column SELECTs);
  restart needs sudo, pending.
- NOT A BUG: the "stuck" result for 105 was a false alarm. Ingestion ran exactly at
  kickoff + RESULT_DELAY (21:30 UTC) and settled the match (Qwen +382,500 on the draw);
  earlier "scheduled" readings were taken before it was due, compounded by an ad-hoc
  query comparing ISO 'T' timestamps against `datetime('now')` (space separator) —
  string comparison silently excludes same-day fixtures.
