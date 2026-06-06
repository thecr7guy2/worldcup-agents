# World Cup Agents — Design Spec

A competition where multiple LLMs act as **virtual gamblers** predicting World Cup 2026
matches. All agents receive the *same* curated information; the only variable is the
reasoning engine. We measure who reasons best under uncertainty.

Status: **DESIGN — not yet implemented.** Tournament kicks off 2026-06-11.

---

## 1. Core principle (the experiment)

Hold the information constant, vary only the model. A single **Intelligence Agent**
gathers all information and produces one frozen **Match Briefing** that every prediction
agent consumes identically. No prediction agent browses on its own → no unfair info edge.

**Facts vs. judgment (the load-bearing rule):** the KB / briefing holds *facts* (results,
form, injuries, odds, post-match recaps). Predictions are *judgment* (who wins, how much
to stake). **Share the facts, never share the judgment.** Sharing one KB does NOT make
predictions converge — each model reasons over identical facts independently, so diversity
of opinion comes from the *reasoning*, not from unequal information. This is what makes the
leaderboard attributable to model skill rather than luck-of-the-search.

---

## 2. Roles

### Intelligence Agent (one model, has tools)
- Gathers from: curated data files, odds API, RSS/news, live web search.
- Produces one **Match Briefing** per fixture (frozen, timestamped).
- After each match finishes, writes a **post-match analysis** into the growing
  **Knowledge Base** (player/coach form, how it went, momentum, injuries).
- Recommended model: Claude (strong tool use / web). Any briefing bias is shared by all
  predictors equally, so it does not break fairness *between* competitors.
- **Neutral-briefing constraint:** the briefing reports facts, never opinions. It may say
  *"Brazil unbeaten in 8; star winger doubtful; market favors them at 1.85"* but must NEVER
  say *"I think Brazil wins."* A predicted lean in the briefing would contaminate every
  model's judgment. Intelligence agent reports; predictors decide.

### Prediction Agents (5 LLMs, reasoning only — NO tools)
All reached via OpenRouter (one key). Slugs verified when wiring the model layer.
1. Claude (Anthropic)
2. GPT-4o (OpenAI)
3. DeepSeek V4   (open-weight)
4. MiniMax M2.7  (open-weight)
5. Kimi K2.6     (open-weight; free variant available)

Each competitor is ONE agent per provider (5 total, NOT 10) that works in **two steps** —
separating football judgment from money judgment, so the payout never biases the pick:

- **Step 1 — PREDICT** (odds hidden): reads the briefing → `{winner, confidence, reasoning}`.
  Pure handicapping, uninfluenced by the market.
- **Step 2 — BET** (same model, now shown odds + bankroll): takes its own step-1 prediction
  + confidence + the 1X2 odds + current bankroll + 25% cap → `{pick, stake}` **or pass**.

Conviction from step 1 is the bridge into step 2 — the stake reflects *how sure* it was.
Hiding odds until step 2 means an agent disagreeing with the bookies does so on football
merit, not because it saw the price first.

### Scoring / Settlement Engine
Settles bets against real results, updates both leaderboards.

---

## 3. Information Layer

The information layer IS the product. Good reports → good competition; noisy reports → the
smartest model predicts garbage. The unit is **per-team, not per-match**.

### The living team dossier (the core unit)
A team's state (form, morale, injuries, who's hot) is a property of the team that EVOLVES
across the tournament. A match is two states colliding. So each team has one living dossier,
updated after every match it plays. Match briefings are cheap assembly from two dossiers —
shared info is NEVER regenerated. This is what keeps cost sane over 104 matches.

### Data lineage
```
  Team DOSSIER (living, updated after every match the team plays)
        │
        ├─ snapshot + fresh news, frozen at cutoff ──► PRE-MATCH REPORT (per team)
        │
   TeamA pre-match report ─┐
   TeamB pre-match report ─┼──► MATCH BRIEFING ──► the 5 predictors
   match context           ─┘     (NO odds here — odds injected at bet step only)
   (H2H, venue, weather, stakes)
        │
   match played
        │
   POST-MATCH analysis (read ONCE) ──► updates BOTH dossiers ──► feeds their NEXT pre-match
```

### Dossier structure — LAYERED to keep recency proportionate
Recency bias ("don't over-emphasize the latest result") is solved by LAYOUT, not by a
"please don't overreact" instruction. The latest match is one bounded, length-capped section
— it nudges form but cannot erase the baseline that says "still a top-8 team."
```
  ┌─ BASELINE (slow-moving)   : underlying quality, ranking, squad class, identity
  ├─ ROLLING FORM (last 5–6)  : trend, not a single result
  └─ LATEST MATCH (bounded)   : one short section, length-capped
```

### Pre-match report contents (rich signal)
- **Form & performance:** last 5–6 results, goals for/against, trend.
- **Availability (highest value):** injuries, suspensions, yellow-card-threshold risk,
  probable XI, rotation risk.
- **Stakes & motivation (the upset goldmine):** must-win vs already-qualified. An
  already-through team resting starters is the #1 World Cup upset generator — prime
  "outside the box" territory.
- **Tactics & matchup:** formation, style, manager, H2H history, stylistic mismatch.
- **Physical:** rest days vs opponent, travel, fixture congestion, fatigue.
- **2026 conditions (real edge this cycle):** heat in US afternoon venues, ALTITUDE in
  Mexico City, match-day weather.
- **Psychology:** pressure, penalty-shootout record, big-tournament temperament.
- **Crowd:** host advantage + diaspora support in North America.
- **Excluded by design:** odds (facts, but injected at the BET step only).

### Post-match report
- Generated per team AFTER the match: what went right/wrong, who played well, momentum.
- **Efficiency:** read the finished match ONCE, write TWO perspective-framed dossier
  updates (TeamA's view, TeamB's view). One article read, two updates.

### Concurrency (many simultaneous kickoffs)
Per-team independence makes report generation embarrassingly parallel. A scheduler fires a
**report batch** at a fixed lead time before each kickoff slot; for every match in the slot
it ensures both teams have a fresh report, fanned out concurrently with a concurrency cap
(API rate limits) + retries. A team plays once per matchday → reports auto-deduplicated.
NOTE: the final group matchday has SIMULTANEOUS kickoffs by FIFA rule (anti-collusion), so
peak load is real — but it's just "more parallel tasks in one batch," not a harder problem.

### Cold start
Match 1 has no post-match history → dossiers built purely from pre-tournament data
(qualifiers, friendlies, rankings, squads). Dossiers get rich by the knockouts. Designed
for from day one.

---

## 4. Temporal integrity (THE integrity rule)
The briefing for match N may contain **only** information that existed **before** match N
kicks off. Post-match analysis of match N feeds match N+1 onward — never its own
prediction. Enforced with a hard timestamp cutoff per briefing. If this leaks, the entire
leaderboard is meaningless.

---

## 5. The gambler model (primary mechanic)

Each agent is a gambler with a bankroll. The math itself punishes chalk and rewards
correctly-seen upsets — no hand-tuned anti-favorite rules needed.

- **Starting bankroll:** $1,000,000 each.
- Before each match the agent sees the frozen briefing + **market odds**.
- The agent chooses predictions **and stake** per market, and **may stake $0 / skip**.
- Settle against real odds: longshot hit → bankroll jumps; favorite → barely moves;
  big bet missed → bleeds. "Always pick favorite" stagnates and loses.
- **Mindset induction:** identical "$1M bankroll, your life depends on growing it, bet big
  only where you see value, don't gamble every match" system prompt for ALL agents
  (keeps the experiment fair — only the model differs).

### Betting market — WINNER ONLY (v1)
- **1X2 (match result):** home / draw / away — settled on **90-minute** result.
- That's the only prediction and the only bet. No scorer, no exact score in v1.
  (Dropped to keep it simple; 1X2 odds are trivially available from any odds API.)

### Passing & idle decay (anti-cowardice)
- **Passing is allowed and legitimate** — betting only where there's value is a core gambler
  skill; forcing a bet every match would punish exactly the discipline we want to reward.
- **Why a passer is a real benchmark:** betting into bookmaker odds is slightly -EV (the vig),
  so an agent that passes everything and holds $1M is the "no edge, no risk" null hypothesis.
  Beating it requires genuine predictive edge over the market — which is the skill we measure.
- **The exploit it creates:** if all models are mediocre, a pure-passer wins by doing nothing.
- **Guardrail — idle-cash decay:** un-staked bankroll bleeds a small % each matchday (~0.25–
  0.5%, TUNABLE). Skipping one match is negligible; passing 100+ matches guarantees you slide
  below $1M. Tactical passing stays viable; winning-by-cowardice does not. A0 — tune the rate.

### Bust rule — cap + re-buy
- **Per-match stake cap:** 25% of current bankroll per market (no round-1 wipeouts).
- **Bust:** if bankroll drops below a floor (~$10k), grant ONE smaller re-buy ($100k =
  10% of start), flagged as a "second life." Keeps all 5 in the race to the final.

---

## 6. Two leaderboards
| Leaderboard | Measures | Question answered |
|---|---|---|
| **Bankroll** (primary) | prediction + risk management | "Best *gambler*?" |
| **Accuracy points** (secondary) | raw correctness, stakes ignored | "Best *predictor*?" |

Accuracy points: correct winner = 1 (hit-rate). Still meaningful vs bankroll — an agent
can pick winners well but bet timidly (high accuracy, low bankroll) or vice versa.

---

## 7. Settlement edge cases (bookmaker conventions)
- **Knockout ET/penalties:** 1X2 settles on **90 mins**. A 1–1 won on pens settles as a
  *draw* (the 1X2 stake on either team loses). (Optional later: separate "to qualify"
  market counting pens.)
- **Postponed/abandoned:** bet void, stake refunded.

---

## 8. Stack
- **Language:** Python.
- **Framework:** Pydantic AI (type-safe structured outputs + the intelligence agent's
  tool/web-search loop). No LangChain.
- **Model access:** ALL 5 models + the intelligence agent via **OpenRouter** — one key, one
  OpenAI-compatible endpoint. Dropped LiteLLM (OpenRouter already unifies providers at the
  gateway, so LiteLLM was a redundant second layer).
- **Telemetry:** every LLM call's token/cost usage (OpenRouter returns *actual billed* cost +
  native token counts in each response) is logged to a `model_call` table — so the technical
  report can JOIN cost/tokens against predictions (cost-per-correct-prediction, etc.).
- **Persistence:** SQLite (stdlib, no ORM) for all structured state; the whole competition is
  one portable `.db` file.

---

## 9. Data sources (updated 2026-06-05 — API-Football dropped)

> **Pivot:** API-Football free plan is locked to seasons 2022–2024 and cannot serve 2026
> fixtures/results. No Pro upgrade. Full rationale in `tasks/todo.md §0`.

Consolidates to TWO free APIs + the LLM's own web search.

| Need | Source | Tier | Key facts |
|---|---|---|---|
| **Schedule seed** (104 fixtures, all 48 teams, UTC kickoffs) | **openfootball/worldcup.json** | free / no key | `GET https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json`. Group + knockout matches. 24 h disk cache. |
| **1X2 odds** (home/draw/away, decimal, consensus) | **The Odds API** | Free 500 credits/mo | sport=`soccer_fifa_world_cup`, `markets=h2h`, `regions=eu`. 1 credit/call. Median across books → one `OddsSnapshot(bookmaker="consensus")` per event. |
| **Results / form / injuries / news** | **Intelligence Agent web search** | free | Gathered at briefing time. Temporal-integrity cutoff enforced by `PreMatchReport.cutoff_at`. |

**Canonical IDs:** normalized team name is the canonical key; `team.id` is a 1-based index
into the frozen `CANONICAL_TEAMS` list in `sources/names.py`; `fixture.id` is openfootball's
`num` when present, else minted by `(date, time, team1, team2)` sort order.

## 10. Open risks / assumptions to validate
- ~~R1 — Anytime-scorer odds availability.~~ **RESOLVED** by going winner-only.
- ~~R2 — Odds snapshot timing.~~ **RESOLVED**: we poll The Odds API live endpoint and persist our own snapshot.
- ~~R3 — API-Football free 100/day~~ **RESOLVED (dropped)**: replaced by openfootball + web search.
- **R4 — Name drift:** The Odds API may rename a team mid-tournament. The alias map in
  `sources/names.py` is the fix point; add entries there if an event starts failing.

## 11. Deployment & runtime

Develop on the Mac (fast loop); run the LIVE competition on an always-on Linux home server
(a laptop). Predictions fire on a schedule tied to real kickoffs across ~6 weeks, so the
orchestrator must live on the always-on box, not the dev Mac.

- **Model access = OpenRouter** (one key). Pydantic AI points at OpenRouter's OpenAI-compatible
  endpoint; we log per-call usage to the `model_call` table for the report.
- **No GPU / local inference.** All 5 competitors + intelligence agent are HOSTED via OpenRouter;
  the open-weight models (DeepSeek V4, MiniMax M2.7, Kimi K2.6) are far too large for a laptop.
  The server just makes HTTP calls, so its specs barely matter.
- **Single-gateway tradeoff:** routing all models through OpenRouter is one point of failure;
  acceptable for a hobby run (retry the matchday on outage), and OpenRouter has internal
  provider fallbacks.
- **Portability (build for it from day one):** git is the only bridge (code only); `uv` +
  `uv.lock` rebuild an identical env on Linux; SQLite is one file that lives on the server;
  `.env` with real keys lives ONLY on the server, never in git; the DB never travels via git.
- **Deploy = `git clone` → `uv sync` → create `.env` → run.**
- **Scheduler:** systemd timers (preferred on Linux) or cron, invoking the matchday pipeline.
- **Cutover:** build/test on Mac → deploy + full dry-run on the server a few days BEFORE
  June 11 (opening match = first hard deadline) → run live from the server; keep pushing
  fixes from the Mac and pulling on the server.
- **A1 — Stake cap 25%, re-buy $100k, floor $10k** — assumed defaults, easy to tune.
- **A2 — Intelligence agent = Claude** — assumed; swap freely.
- **A3 — One briefing per match** (not per-agent) — core to fairness.
