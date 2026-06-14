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

### Prediction Agents (7 LLMs, reasoning only — NO tools)
All reached via OpenRouter (one key). `config.PREDICTION_MODELS` is the canonical lineup
(slugs drift as providers ship new versions — edit there, not here). At kickoff 2026 it is:
1. GPT 5.5 (OpenAI)
2. Opus-4.8 (Anthropic)
3. Gemini-3.1-Pro (Google)
4. DeepSeek-V4-Pro (open-weight)
5. MiniMax-M3 (open-weight)
6. Kimi-K2.6 (open-weight)
7. Qwen3.7-Max (open-weight)

Each competitor is ONE agent per provider (7 total, NOT 14) that works in **two steps** —
separating football judgment from money judgment, so the payout never biases the pick:

- **Step 1 — PREDICT** (odds hidden): reads the briefing → `{winner, confidence, reasoning}`.
  Pure handicapping, uninfluenced by the market.
- **Step 2 — BET** (same model, now shown odds + bankroll): takes its own step-1 prediction
  + the 1X2 odds + current bankroll → an eligible `{pick, stake_pct}` **or pass**. An outcome
  is eligible only when its immutable Step-1 probability is within 10 percentage points of
  the model's top read. Odds can choose among those football-plausible outcomes, but cannot
  turn a clearly unlikely longshot into a bet. The engine never substitutes a pick.

Every new prediction and bet also persists an explicit experiment phase, prompt/rules
version, requested model ID, OpenRouter generation ID, and Git revision. Bets additionally
store the bookmaker + capture timestamp of the exact odds snapshot shown at Step 2. These
fields are observational only: they make phase comparisons and report claims reproducible
without changing the model's pick or the engine's final action.

The `bet` row preserves both sides of deterministic enforcement: `requested_*` is the
model's parsed pick and tier-derived dollar request before guards; `pick/stake` is the final
action used by settlement. `engine_adjustment` records why they differ (`ineligible_pick`,
`invalid_tier`, `stage_cap`, `exposure_cap`, …). The exact provider response remains linked
in `model_call`. Legacy revised-probability columns remain nullable for historical rows.

**Coherent tier betting (Phase 6).** The immutable odds-hidden distribution is the
football guardrail. Let `p_top` be the highest Step-1 probability; outcome `i` is bettable
when `p_top - p_i <= 0.10`. The model may choose any eligible outcome after seeing the odds,
or pass. This preserves a value bet on a genuine close second (`40/25/35`) while blocking a
large wager on an outcome the same model rated clearly unlikely (`53/26/21`).

Stake sizing uses fixed conviction tiers instead of Kelly or an EV formula:

- Group: 5%, 10%, 15%, 20%.
- Round of 32 / Round of 16: add 25%.
- Quarterfinal onward: add 30%.

The engine validates the tier, applies the stage ceiling, and trims only for the existing
50% aggregate-exposure budget. There is no revised probability, EV gate, market blend,
Kelly sizing, or minimum stake floor. Passing is explicitly normal when no eligible price
deserves money; the prompt no longer pressures agents to bet every real lean. A malformed
Step-2 JSON response gets one format-only retry; parsed semantic violations are enforced
without asking the model to reconsider its decision.

Conviction from step 1 is the bridge into step 2 — the stake reflects *how sure* it was.
Hiding odds until step 2 means an agent disagreeing with the bookies does so on football
merit, not because it saw the price first.

> **Historical Phase 2-5 note:** blind
> Step-1 distributions proved systematically FLATTER than the market — every model landed
> near ~45/30/25 regardless of matchup, ~10–15 points under the market on clear favorites.
> With the EV guard judged at those blind numbers, no short-priced favorite could ever be
> bet (p × odds < 1 by construction) while every underdog showed a phantom 15–35% edge —
> so all seven agents predicted the favorite and bet the dog, every match with a clear
> favorite (see fixtures 103/105 vs the near-even 104). Judging EV at a post-market revised
> probability was introduced to repair that issue, followed by EV/Kelly risk controls.
> Production Phase 5 still produced zero favorite bets across its first 28 decisions:
> models used the price to narrate longshot value against their own read. Phase 6 therefore
> replaces the probability machinery with the simple Step-1 eligibility rule above.

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

Each agent is a bettor with a bankroll. Football judgment determines what is plausible;
market prices determine which plausible outcome is worth backing.

- **Starting bankroll:** $1,000,000 each.
- Before each match the agent sees the frozen briefing + **market odds**.
- The agent chooses an eligible outcome and fixed conviction tier, and may pass.
- Settle against real odds: longshot hit → bankroll jumps; favorite → barely moves;
  big bet missed → bleeds. "Always pick favorite" stagnates and loses.
- **Mindset induction:** identical "grow the bankroll without abandoning your blind football
  read; large bets are allowed; passing is normal" system prompt for ALL agents.

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
- **Per-match stake cap:** fixed tiers with a stage ceiling: 20% in groups, 25% in the
  round of 32/16, and 30% from the quarterfinals onward.
- **Bust:** if bankroll drops below a floor (~$10k), grant ONE smaller re-buy ($100k =
  10% of start), flagged as a "second life." Keeps all 5 in the race to the final.
- **Settlement granularity = the matchday, not the fixture.** A whole UTC day settles as
  one batch once all its fixtures are resolved, and the bust check runs *once* over the
  day's total PnL. This makes the life-burn independent of the order fixtures settle in: a
  competitor can't be tipped into a re-buy by a mid-day dip that a later same-day win would
  have erased. (Bankroll is net-PnL — stakes are never escrowed — so the day's end balance
  is order-free regardless; only the intermediate floor check was order-sensitive.
  `settlement.settle_matchday` is the enforcement point; impact lands a few hours later on
  busy days, a deliberate trade.)
- **Concurrent exposure = informed and bounded.** Stakes aren't escrowed, so on a busy
  matchday — especially the final group round, where each group's two matches kick off
  *simultaneously* (anti-collusion) — an agent can bet several still-unsettled matches off
  one bankroll. The bet step tells the agent its open exposure and the engine caps aggregate
  unsettled stake at 50% of bankroll. `db.open_exposure` + `predict._exposure_note` are the
  touchpoints. (Temporal integrity is
  unaffected: bets lock ~0.83h before kickoff and results aren't ingested until ~2.5h after,
  so an agent never sees a simultaneous match's result when betting its sister fixture.)

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
- **A1 — Stage tiers 20/25/30%, re-buy $100k, floor $10k** — current defaults, easy to tune.
- **A2 — Intelligence agent = Claude** — assumed; swap freely.
- **A3 — One briefing per match** (not per-agent) — core to fairness.

## 12. Report instrumentation (added 2026-06-10, day before kickoff)

The competition mechanics above are frozen; this section is the **measurement layer** for
the final technical report. None of it feeds back into predictions, bets, briefings, or
dossiers — it only records more.

- **Verbatim capture per LLM call** (`model_call`): `response_text`, `reasoning_text`
  (provider-exposed trace), `prompt_text` (late updates make inputs time-varying — record,
  don't reconstruct), `annotations_json` (web-search citations behind each briefing/result).
- **Factor attribution** (`prediction.key_factors`): each forecast names 3-6 short tags for
  what drove it → per-model "what does this model weigh" charts, and factor-vs-correctness.
- **Tournament outlooks** (`tournament_outlook`, `outlook.py`): every competitor interviewed
  with NO briefing/odds/web at named phases (`pre`, `post_group`, `pre_final`, `post_final`):
  champion, runner-up, semifinalists, dark horses, golden boot, worldview. Measures priors,
  gradeable foresight, and belief revision. Write-only report data; never fed back.
- **Near-kickoff odds refresh** (`orchestrate.odds_refresh_due` + `ingest.poll_odds`): when a
  fixture inside the late-update horizon has missing/stale (>45 min) consensus odds, the tick
  spends one extra Odds API credit so bets are placed into a fresh line — and the report gets
  a true closing-line-value reference. Also self-heals fixtures the 6-hourly poll missed.
- **Result double-read** (`RESULT_CONFIRM_READS=2`): a 90' score is written only when two
  independent web-search reads agree — a wrong score would corrupt settlement + dossiers
  irreversibly.
- **Nightly DB backup** (`scripts/backup_db.py`, wc-backup.timer / cron): the .db IS the
  experiment; snapshot daily, 21-day retention.
