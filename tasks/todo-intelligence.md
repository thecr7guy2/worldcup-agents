# Slice: Intelligence Layer (web-search dossiers → pre-match reports → match briefing)

**Status:** IN PROGRESS. **Executor:** Opus (built directly — long-pole/high-risk piece).
**Read first:** `tasks/DESIGN.md §1–4` (facts-vs-judgment, dossier layering, temporal integrity).
Previous slice (ingestion) is complete — see `tasks/todo.md`.

---

## 0. Grounding facts (verified 2026-06-05, do not re-probe)

- OpenRouter key is **funded** (`GET /key` → `is_free_tier:false`, `limit:null`, ~$0.013 spent).
  → the **web-search plugin works** (`plugins:[{"id":"web"}]`, billed in `usage.cost`, already
  captured by `ModelCall`). This is the L1 discipline: capability verified on the real key first.
- `llm.py` is a hand-rolled OpenRouter httpx client (NOT pydantic-ai). We extend it with web
  search rather than introducing the full pydantic-ai agent loop — smallest change that works.
- All dossier/report/briefing **tables already exist** in `db.py`; only round-trip helpers and the
  agent logic are missing.
- Intelligence model = `config.INTELLIGENCE_MODEL` (free lineup → nemotron). Account is funded, so
  the user may flip `use_free_models=false` for a stronger analyst — respect the config, don't
  silently override; recommend after observing output quality.

## 1. Architecture (per DESIGN §3 — briefings are CHEAP ASSEMBLY, never regenerated)

```
build_dossier(team)        web search → layered TeamDossier (baseline/rolling_form/latest) — REUSABLE per team
build_pre_match_report     dossier + fresh news, frozen at cutoff → PreMatchReport (per fixture,team) — NO odds
build_match_context        web search → neutral per-fixture context (H2H, venue/altitude/weather, stakes)
assemble_briefing          DETERMINISTIC string assembly: reportA + reportB + context → MatchBriefing — NO odds, NO LLM
brief_fixture              orchestrates the above lazily + idempotently
```

Reuse: dossiers are built once per team and reused across that team's matches. Reports/context are
per-fixture. The briefing is assembled (no LLM call) so shared facts are never regenerated and no
re-summarization can inject a lean or drop facts.

## 2. Load-bearing constraints (baked into prompts; breaking any silently corrupts the experiment)

- **Neutral.** Facts only, never opinions/predictions/leans. No "I think X wins", no win probability.
- **No odds.** Never mention odds/market/implied prob — injected only at the bet step.
- **Temporal integrity.** `cutoff_at` recorded per report; generate strictly BEFORE kickoff; instruct
  the model to use only info known as of the cutoff and to say nothing about the match itself.
- **Layered dossier.** baseline (slow) / rolling_form (last 5–6) / latest_match (bounded) — recency
  stays proportionate by LAYOUT, not by an instruction.
- **No fabrication.** Omit unverifiable facts rather than guess; no invented scores/injuries.

## 3. Acceptance criteria

1. `python -m worldcup_agents.intelligence brief <fixture_id>` produces & persists a `MatchBriefing`
   for a real group fixture (verify on the opener, Mexico vs South Africa).
2. Briefing contains **both** teams' reports + a match-context block; contains **no** odds/price terms
   and **no** first-person lean (grep guard for "odds","i think","will win","should win").
3. Dossiers persisted for both teams with all three layered sections non-empty.
4. Pre-match reports persisted with `cutoff_at < kickoff`.
5. Re-running `brief` is idempotent (reuses existing dossiers/reports; no duplicate rows).
6. Every LLM call logged to `model_call` (step in {dossier,pre_match,match_context}).
7. `ruff check` + `black --check` clean.

## 4. Checklist (one in-progress at a time)

- [ ] `llm.py`: add `web_search`/`web_max_results` to `complete()` (OpenRouter `web` plugin).
- [ ] `db.py`: add round-trip helpers for dossier / pre_match_report / match_briefing.
- [ ] `intelligence.py`: prompts + the 5 functions above + argparse CLI (`brief`, `dossier`).
- [ ] Verify on the opener against the live `worldcup.db` (read-only re: existing data); grep guards.
- [ ] `ruff check` + `black .`; fill Results; log any lesson.

## 5. Working notes / decisions
- 2026-06-05: web search via OpenRouter plugin (not a pydantic-ai tool loop) — fits llm.py, funded key.
- Briefing = deterministic assembly (DESIGN §3 "cheap assembly; shared info NEVER regenerated").

## 6. Results (2026-06-05 — COMPLETE)
- **Files touched:**
  - `src/worldcup_agents/llm.py` — added `web_search`/`web_max_results` to `complete()` (OpenRouter
    `web` plugin; search cost flows into the existing `ModelCall.cost_usd` telemetry).
  - `src/worldcup_agents/db.py` — round-trip helpers: `upsert_dossier`/`get_dossier`,
    `upsert_pre_match_report`/`get_pre_match_report`, `upsert_match_briefing`/`get_match_briefing`.
  - `src/worldcup_agents/intelligence.py` (NEW) — `build_dossier` (layered, reusable),
    `build_pre_match_report` (frozen at cutoff), `build_match_context`, `assemble_briefing`
    (deterministic, no LLM, no odds), `brief_fixture`, + `brief`/`dossier` argparse CLI.
    Helpers `_split_sections` (glued-header tolerant) and `_strip_preamble` (kills search narration).
- **How verified:** seeded throwaway `/tmp/wc_intel.db`, ran `intelligence brief 103` (opener,
  Mexico vs South Africa) end-to-end against live web search. All 7 ACs pass:
  briefing persisted with both reports + context; **0** odds/lean terms (grep guard, footer excluded);
  both dossiers have 3 non-empty layered sections; pre-match `cutoff_at < kickoff`; `model_call`
  logged for steps {dossier, pre_match, match_context}; **idempotent** re-run (0.27s, 0 new LLM
  calls, byte-identical briefing). `ruff` + `black --check` clean across the package.
- **Quality notes / follow-ups:**
  - Temporal discipline held in practice — the SA report self-noted "result not yet available as of
    June 5" for an unplayed friendly.
  - The **free** intelligence model (nemotron) showed minor *factual* inconsistencies across calls
    (e.g. SA qualifying group/record stated two ways). Architecture is sound; if briefing fidelity
    matters, flip `use_free_models=false` for a stronger analyst — the OpenRouter account is funded.
  - **Post-match reports / dossier updates — NOW BUILT (2026-06-05).** `db.upsert/get_post_match_report`
    added; `intelligence.build_post_match_report` (neutral recap, fixed `**What happened** / **Standout
    performers** / **Fitness & momentum**` headers, web search, persisted to `post_match_report` only
    when fixture-keyed) + `update_dossier_after_match` (refreshes `rolling_form`+`latest_match`, keeps
    `baseline`) + `postmatch` CLI. Demoed on Mexico 5-1 Serbia (Jun 4 friendly): dossier `latest_match`
    correctly moved Australia→Serbia, rolling_form folded in the 8-match unbeaten run. No odds/lean.
    The same function serves the tournament path (settlement will pass the finished fixture's teams).
  - Model lineup switched: intelligence agent is now **DeepSeek V4 Pro** (was Opus 4.8) — ~40× cheaper,
    richer/cited briefings; see memory `no-free-models`. Free option removed from `config.py`.
  - **Markdown is now consistent** across teams/fixtures: pre-match reports use fixed `**Availability**
    / **Form & trend** / **Stakes & motivation** / **Tactics & matchup** / **Rest & conditions** /
    **Psychology & crowd**`; match context uses `**Head-to-head** / **Venue & conditions** /
    **What's at stake**`. (Earlier each call free-styled its own headers.)
  - Batch/scheduled briefing generation (all fixtures in a matchday slot, concurrency-capped) is a
    later slice; this proves the per-fixture unit.
