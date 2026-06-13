# Reasoning leaderboard via proper scoring (Brier)

## Why
Bankroll is high-variance (one lucky underdog swings it) and, post market-reconciliation,
risks measuring "who copies the line" not "who reasons." A proper scoring rule (Brier) on
the BLIND Step-1 distribution is low-variance, attributable to probability judgment, and —
crucially — made before odds are shown, so market-copying cannot contaminate it. All inputs
(`p_home/p_draw/p_away` + 90' result) are already stored: pure-additive, no migration.

## Scope (this slice)
- [x] Commit + push the already-running market-reconciliation change (separate commit).
- [ ] `leaderboard.brier_standings()` — multi-class Brier over graded predictions, ascending.
- [ ] CLI `brier` board + uniform baseline (~0.667) for reference.
- [ ] `web/stats.leaderboard_brier()` + `/api/leaderboard/brier` route (additive, read-only).
- [ ] Verify on a COPY of the live DB (zero risk to live run).
- [ ] Commit + push.
- [ ] Deploy: reconcile server git, pull. Flag sudo restarts (wc-api) for the user.

## Out of scope (follow-up, flagged to user)
- Next.js public page for the reasoning board (needs web rebuild + sudo restart I can't do).
- Brier of `p_revised` vs blind `p` to validate the market step (needs Phase-2 bets first;
  0 exist yet).

## Acceptance
- `brier` board prints per-model average Brier (lower=better) + graded count, ordered.
- Numbers reproduce by hand on one fixture.
- API route returns the same data; no migration; legacy rows without a distribution skipped.
