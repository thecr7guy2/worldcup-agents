# Step-2 market reconciliation (revised probability)

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
- [x] EV guard runs on `p_revised` (fallback: Step-1 probability when missing/invalid).
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
  bets unaffected.

## Acceptance criteria

- A model that revises its pick's probability above break-even + 0.05 can now bet a
  short-priced favorite (impossible before).
- A bet whose revised probability fails the threshold is auto-passed with the EV note
  naming "revised probability" as the basis.
- A response with no/invalid `p_revised` behaves exactly like the old guard (Step-1
  fallback), tagged "(no revised given)".
- Live DB migrates additively; existing rows and the web app keep working.

## Phase marker (for the tech report)

Fixtures up to and including 105 (Canada–BIH, 2026-06-12) were decided under the old
blind-EV regime — treat as Phase 1 (shared-miscalibration mechanism). Fixtures predicted
after 2026-06-13 ~01:50 UTC run under the revised-probability regime — Phase 2
(market-update skill). In `bet` rows, Phase 2 LLM bets carry non-NULL `p_revised`.

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
