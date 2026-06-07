# todo-website.md — The showcase site ("The Arena")

A public, super-cool showcase for the LLM World Cup betting competition: agents as
video-game characters with stat sheets, World Cup fixtures with flags, leaderboards,
and full money/token transparency. Live backend reading the real SQLite state.

## Design Read (taste-skill §0)

> Reading this as: a **showcase + live-data site** for an AI-vs-AI World Cup betting
> experiment, audience = tech-curious followers and the builder showing it off, with a
> **video-game-meets-sports-broadcast** language, leaning toward a dark "arcade trading
> floor x stadium" aesthetic — Tailwind v4 + Motion + Phosphor icons, mono numerics,
> flag SVGs.

**Dials (taste-skill §1):** `DESIGN_VARIANCE 7 / MOTION_INTENSITY 6 / VISUAL_DENSITY 7`.
Bold asymmetric showcase surfaces; stat-dense character cards and telemetry; motion that
is *motivated* (entrance reveals, count-up bankrolls, hover physics, live ticker) and
collapses under `prefers-reduced-motion`.

**Theme lock:** one dark theme (off-black `zinc-950` base, never pure `#000`). **One global
accent** (electric stadium-lime) for all interactive/CTA. Each agent additionally gets a
distinct *kit color* used ONLY inside its own character card/avatar — a documented per-entity
rule (like a team kit), not a second page accent. No AI-purple, no em-dashes (§9.G), real
flag SVGs not emoji, simple geometric agent sigils only (no hand-rolled decorative SVG slop).

## Current data reality (verified against live DB, 2026-06-07)

Pre-kickoff. 7 competitors all at $1M / 0 lives. 104 fixtures all `scheduled`
(72 group w/ real teams, 32 knockout placeholders), June 11 → July 19. 216 odds snapshots.
Teams have NO country codes (build name→ISO2 flag map). Zero predictions/bets/settlements/
telemetry until the tournament runs. **The site must be beautiful empty and light up
automatically as data flows.**

## Architecture

- **Backend: FastAPI**, added via `uv add fastapi uvicorn[standard]`. Reuses `db.py` +
  `leaderboard.py` (no logic duplication / drift). Opens the live `worldcup.db` **read-only**
  (`file:...?mode=ro`). New package `src/worldcup_agents/web/`.
- **Frontend: Next.js 15 (App Router, React 19) + Tailwind v4 + Motion (`motion/react`) +
  Phosphor.** Lives in `web/`. Server Components fetch from the FastAPI API; a Next.js
  `rewrites()` proxy maps `/api/*` → the local uvicorn process so the browser sees one origin.
  Light chart lib (`recharts`) for bankroll-history sparklines.
- **Flags:** name→ISO-3166 alpha-2 map in the backend; render via `flagcdn.com` SVGs.
  Knockout placeholders show their bracket label until resolved.
- **Deploy delta (call-out):** server gains a **Node** dependency (build + run the Next
  server). Two systemd units: `uvicorn` (API, 127.0.0.1:8001) and `next start` (web, :3000),
  with Next rewriting `/api/*` to the API. Deploy: `git pull → uv sync → (cd web && npm ci &&
  npm run build) → restart both units`. Always-on home server we control, so acceptable.

### Read-only JSON API
- `GET /api/overview` — status, counts, date range, totals (staked, tokens, cost), days-to-kickoff
- `GET /api/competitors` — roster + computed stats: bankroll, ROI, accuracy, W/L record,
  streak, lives, tokens, cost, derived archetype ("High Roller" / "Sharpshooter" / "Cautious")
- `GET /api/competitors/{name}` — detail: bankroll_history, bets, predictions, reasoning
- `GET /api/leaderboard/bankroll` and `/api/leaderboard/accuracy` (reuse `leaderboard.py`)
- `GET /api/fixtures?day=&stage=` — resolved team names + flags + consensus odds + status + result
- `GET /api/fixtures/{id}` — full board: predictions → bets → settlements per model
- `GET /api/telemetry` — `usage_by_model` + per-step + cost-per-correct-prediction
- `GET /api/today` — today's fixtures

### Frontend surfaces (SPA routes)
1. **Arena (Home)** — hero, today's matches (flags), leaderboard podium, headline totals,
   how-it-works pipeline explainer (facts → judgment, the load-bearing invariant).
2. **Roster** — 7 agent character cards → **Character detail** (full stat sheet, HP-style
   bankroll bar vs $1M, hearts for lives, bankroll history chart, bet log, sample reasoning).
3. **Leaderboards** — bankroll (primary) + accuracy (secondary).
4. **Fixtures** — schedule with flags; **Fixture detail**: per-agent prediction → bet → settle.
5. **Lab (Telemetry)** — tokens + cost per model, per step, cost-per-correct, total spend.

## Slices (thin vertical, verify each)

- [x] **S1 Backend skeleton** — FastAPI app, read-only DB dep, `/api/overview` + `/api/competitors`
      (computed stats + archetypes). Verified via TestClient against the snapshot.
- [x] **S2 Rest of API** — fixtures (+flags map), fixture detail, leaderboards, telemetry, today.
      Verified: every endpoint 200; knockout placeholders + empty-data handled.
- [x] **S3 Frontend scaffold** — Next.js 15 / Tailwind v4 / Motion / Phosphor, design tokens,
      theme lock, app shell + nav, Arena page. Verified: dev server + screenshots.
- [x] **S4 Roster + character detail** — character cards, head-to-head table, profile + chart + log.
- [x] **S5 Fixtures + fixture detail** — stage filter, flag rows, per-fixture prediction/bet/settle board.
- [x] **S6 Leaderboards + Lab** — bankroll + accuracy boards, telemetry dashboards.
- [x] **S7 Polish + deploy** — empty/loading/error states, mobile responsive, reduced-motion,
      §14 pre-flight pass, `next build` green, wc-api + wc-web systemd units + deploy runbook.

## Results (what shipped, how verified)

**Backend** — `src/worldcup_agents/web/` (`app.py`, `stats.py`, `flags.py`, `agents_meta.py`).
FastAPI over a **read-only** sqlite connection, reusing `db.py` + `leaderboard.py` so the site
can never drift from the engine. 9 endpoints. Verified in-process (Starlette TestClient) and by
live curl against a snapshot of the server DB.

**Frontend** — `web/` Next.js 15 (App Router, RSC) + Tailwind v4 + Motion + Phosphor + Recharts.
7 routes (Arena, Roster, agent profile, Leaderboard, Fixtures, fixture detail, Lab). Server
Components fetch the API; `next.config.ts` rewrites `/api/*` to uvicorn (one origin). `next build`
passes clean (types valid, 8 routes). Screenshotted every page at desktop + mobile via headless
Chrome.

**Design** — `design-taste-frontend` skill applied throughout. Dials 7/6/7. One locked lime accent
+ per-agent kit colors confined to cards. Zero em-dashes (grepped). Real flag SVGs. Single dark
theme (intentional for an arcade/stadium product). §14 pre-flight run; copy tightened to pass.

**Deploy** — `deploy/wc-api.service` + `deploy/wc-web.service` + `deploy/install-web.sh`
(matches existing token-substitution convention), runbook appended to `deploy/README.md`,
`web/README.md` for dev. Node is the one new server dependency (build + run).

**State at build time** — pre-kickoff (first match 2026-06-11): all 7 at $1M, no bets/predictions/
telemetry yet. Site is designed to look complete empty and fill in automatically as data lands.

**Not done deliberately** — no git commit (project rule: commit only when asked). Light mode
skipped (single dark theme is the intended aesthetic). Live multi-day data not yet present to
exercise the populated states end-to-end (will appear once the tournament runs).

## Acceptance criteria
- A visitor with zero prior context understands: who the 5–7 agents are, how the game works,
  who's winning (bankroll + accuracy), today's/upcoming matches with flags, and exactly how
  much money/tokens each agent has spent.
- Reads **live** server state (no mock data); degrades gracefully pre-kickoff and fills in
  automatically as predictions/bets/results land.
- Passes the taste-skill §14 Pre-Flight Check (no AI tells, em-dash ban, theme/color/shape
  locks, motivated motion, reduced-motion, real flag assets, sane empty states).

## Verification story (no test suite in repo)
Per repo convention: inline `uv run python -c` checks for API shape against the local snapshot;
manual API curl; frontend screenshots in both motion settings; final pass on a synced copy of
the live DB before deploying.

---

## Revision pass — 2026-06-07 (post-ChatGPT redesign review)

User feedback on the ChatGPT-regenerated site. Two corrections + four additions.

### Corrections — DONE & verified (`tsc --noEmit` clean)
- [x] **Hero title** `Seven AIs. / Betting the / World Cup.` → `7 AIs. / $7M. / One World Cup.`
      (stakes-forward; clearer hook). `app/page.tsx`.
- [x] **Model name is now the hero everywhere; persona NAMES dropped.** The joke names
      (`Goalpost Gambit`, `Bracket Bongo`, …) were the H1 on every surface, burying the real
      model. Flipped so `c.model` is the headline and vendor/position is the subtitle. Kept all
      other persona flavor (tagline, ratings, signature move, kit color). Touched:
      `CharacterCard`, `roster` (+table headers Model/Maker), `agents/[name]` (H1 + empty
      states), `leaderboard` (×2), `lab`, `fixtures/[id]` (×2). Retied colored `sigil`
      monograms from persona initials → model monograms (G5/O4/M3/K2/V4/G3/Q3) in
      `agents_meta.py`. `persona_name` stays in the data/API, just unrendered.
- [x] Supporting copy de-personified: layout meta + footer, roster heading, stat-band sub.

### Graph package (user: "more graphs, decide the best yourself"). Recharts already in deps.
- [x] **Slice 1 — Market/odds graphs (live data TODAY).** `impliedProbs()` helper (decimal odds
      → normalized %, exposes overround). New `MarketBar` (monochrome labelled home/draw/away
      bar) on every `MatchCard` (compact) + a "Market read" card on `fixtures/[id]`. New
      `MarketFavorites` recharts horizontal bar (top-8 favorites by implied win %, click-through)
      in a "Who the market trusts" homepage section. Verified live: homepage + fixture 103 serve
      the sections; 72/104 fixtures have odds. `tsc` clean, `next build` clean.
- [x] **Slice 2 — Bankroll race.** `BankrollRace` (recharts multi-line, forward-fills each
      model's balance across irregular event times) on `/leaderboard`. Server merges 7
      `/competitors/{name}` histories. Pre-kickoff renders a clean "starting grid" (level at $1M)
      with a caption. Verified live on /leaderboard.
- [x] **Slice 3 — Compute/lab technical graphs.** `CostVsAccuracy` (scatter: x=cost, y=hit rate,
      bubble=tokens; joins `telemetry.by_model` × competitor accuracy) + `StepBreakdown` (cost
      stacked by pipeline step). Gated behind `hasData`, so pre-kickoff shows the existing
      "meter starts at kickoff" empty state. Built + typechecked; fills at kickoff.
- [x] **Slice 4 — Per-fixture disagreement.** `Disagreement` (pick-distribution bars +
      confidence-spread dot track, kit-coloured) above the board on `fixtures/[id]`, shown only
      when predictions exist. Built + typechecked; fills when predictions lock.

**Note:** slices 3 & 4 are data-gated and could not be visually verified pre-kickoff (telemetry=0,
no predictions). They build clean and render empty states correctly. To see them full before the
tournament, seed a throwaway DB (the "demo with sample data" option, declined for now).

### Additions — TODO (user picked all four). Constraint: must look great PRE-KICKOFF (zero bets).
- [ ] **A. Live leaderboard hero strip** (highest value). Compact ranked standings near the top
      of the homepage (rank, model, bankroll, ROI). Reuse `/leaderboard` logic. Empty state:
      all tied at $1M → show "awaiting first whistle" ordering by name, not fake movement.
- [ ] **B. How-a-pick-works explainer.** Concrete one-fixture walkthrough: same briefing →
      7 predictions (odds hidden) → bets (odds shown) → settle on 90-min. Pre-kickoff: render
      with a sample/next fixture and placeholder calls so the *flow* is legible with no data.
- [ ] **C. Head-to-head / disagreement view** on `fixtures/[id]`. Summarize where the 7 models
      split (pick distribution, confidence spread). Pre-kickoff: "predictions lock at kickoff".
- [ ] **D. Cost vs performance.** Partly exists in `lab` (`cost_per_correct`, spend-by-model).
      Add a value ranking / scatter: does the pricier model bet smarter? Pre-kickoff: shows
      spend only, lights up accuracy axis after settlements.

**Approach:** build one slice at a time; verify each with API up + dev server screenshots in
both motion settings before moving on. Needs FastAPI (`uv run uvicorn`) + `next dev` running
against the local DB snapshot.
