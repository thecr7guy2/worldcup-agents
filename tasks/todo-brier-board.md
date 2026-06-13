# Reasoning leaderboard via proper scoring (Brier)

## Why
Bankroll is high-variance (one lucky underdog swings it) and, post market-reconciliation,
risks measuring "who copies the line" not "who reasons." A proper scoring rule (Brier) on
the BLIND Step-1 distribution is low-variance, attributable to probability judgment, and —
crucially — made before odds are shown, so market-copying cannot contaminate it. All inputs
(`p_home/p_draw/p_away` + 90' result) are already stored: pure-additive, no migration.

## Scope (this slice)
- [x] Commit + push the already-running market-reconciliation change (separate commit 8d6d7b7).
- [x] `leaderboard.brier_standings()` — multi-class Brier over graded predictions, ascending.
- [x] CLI `brier` board + uniform baseline (0.667) for reference.
- [x] `web/stats.leaderboard_brier()` + `/api/leaderboard/brier` route (additive, read-only).
- [x] Verify on a COPY of the live DB — Gemini avg 0.4431 reproduced by hand; ruff clean.
- [x] Commit + push (85b244b).
- [x] Deploy: server fast-forwarded to 85b244b, uv sync no-op, brier CLI live on prod DB.
      PENDING (user, needs interactive sudo): `sudo systemctl restart wc-api.service`
      — until then /api/leaderboard/brier is 404 and the API won't expose p_revised.

## Web frontend (done — commit 1aa69d8)
- [x] Reasoning section on /leaderboard under accuracy: Brier table + baseline footer +
      plain-English caption. Fetch degrades gracefully (empty state) if route is 404.
- [x] tsc --noEmit clean locally; `npm run build` clean on the server (11/11 pages,
      /leaderboard is dynamic). New .next built on server.
- [ ] PENDING (user, interactive sudo): restart wc-api AND wc-web to serve the route +
      the new build.

## Still out of scope (future)
- Brier of the Phase-4 complete revised distribution vs blind `p` to validate whether
  market reconciliation improves calibration. The required fields now exist; this should
  remain a report/analysis slice rather than changing live betting behavior.

## Acceptance
- `brier` board prints per-model average Brier (lower=better) + graded count, ordered.
- Numbers reproduce by hand on one fixture.
- API route returns the same data; no migration; legacy rows without a distribution skipped.
