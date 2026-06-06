# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A competition where 5 LLMs act as **virtual gamblers** predicting FIFA World Cup 2026
matches. A single intelligence agent gathers facts into shared per-team dossiers; each
competing model reasons over the *same* information and bets a $1M virtual bankroll on the
match winner. The goal is to measure which model reasons best under uncertainty.

**`tasks/DESIGN.md` is the source of truth for the design.** Read it before non-trivial work —
it carries the rationale behind every decision below. `tasks/` is the file-based task/plan log.

## Commands

`uv` is the toolchain (Python 3.11). On this Mac it lives at `~/.local/bin/uv`, which may not
be on the non-interactive PATH — prefix with `export PATH="$HOME/.local/bin:$PATH"` if a
shell can't find it.

```bash
uv sync                          # create venv + install from uv.lock
uv run python -m <module>        # run a module inside the venv
uv run python -c "..."           # one-off checks (used for verification slices)
uv add <pkg>                     # add a dependency (updates pyproject + lock)
```

Secrets live in `.env` (gitignored); template is `.env.example`. `config.Settings` reads them.
There is no test suite yet — each build slice is verified with an inline `uv run python -c`
script against a throwaway DB (see git history / the pattern in prior slices).

## Architecture

Data flows in one direction; the boundaries between *facts* and *judgment* are the whole point.

```
 Intelligence Agent (1 model, has web/tool access)
   → builds per-team DOSSIERS (facts only) → MATCH BRIEFING per fixture (NO odds)
       → 5 Prediction Agents (reasoning only, no tools), each in TWO steps:
            Step 1 PREDICT (odds hidden)  → {winner, confidence, reasoning}
            Step 2 BET     (odds shown)   → {pick, stake} or pass
              → Settlement vs the 90-min result → Bankroll + Accuracy leaderboards
```

### Load-bearing invariants (breaking any of these silently corrupts the competition)

- **Shared knowledge base, never shared judgment.** ONE intelligence agent builds ONE set of
  dossiers that all 5 models read identically. The only variable is the reasoning model — that
  is what makes the leaderboard attributable to skill, not luck-of-the-search. Do not give
  prediction agents their own tools or per-model research.
- **Temporal integrity.** A briefing for match N may contain only information that existed
  *before* match N kicks off. Post-match analysis of N feeds N+1 onward, never N itself.
  `PreMatchReport.cutoff_at` is the enforcement point.
- **No odds in the briefing.** Odds are facts but are injected only at the Step-2 bet stage, so
  an agent's prediction is uninfluenced by the market. Keep `OddsSnapshot` out of prediction inputs.
- **Neutral briefings.** The intelligence agent reports facts ("favored at 1.85"), never
  opinions ("I think Brazil wins"). A predicted lean would contaminate every model.
- **1X2 settles on the 90-minute score.** A knockout 1–1 won on penalties settles as a DRAW.
  `Fixture.result_90()` is the single source for this; `advanced_id` records who progressed.

### Code layout (`src/worldcup_agents/`)

- `config.py` — `Settings` (env-loaded secrets; one `OPENROUTER_API_KEY` for all models), the
  **model registry** (`PREDICTION_MODELS` + `INTELLIGENCE_MODEL` as `ModelSpec`s mapping display
  name → OpenRouter model id), `OPENROUTER_BASE_URL`, and tunable competition constants
  (`STARTING_BANKROLL`, `MAX_STAKE_FRACTION`, `IDLE_DECAY`, `BANKRUPT_FLOOR`, `REBUY_AMOUNT`,
  `MAX_LIVES`).
- `models.py` — all Pydantic domain shapes + enums; the validated types that cross every
  boundary. Storage mirrors these. Includes `ModelCall` (per-call token/cost telemetry).
- `db.py` — stdlib `sqlite3` (no ORM). `SCHEMA_SQL`, `connect()` (foreign keys ON),
  `init_db()` (idempotent + seeds competitors at $1M), typed round-trip helpers, and telemetry
  (`log_model_call`, `usage_by_model`) for the report.

## Conventions

- **Canonical key = normalized team name; integer IDs are locally-minted surrogates.**
  Schedule spine: `openfootball/worldcup.json`; odds: The Odds API. API-Football is
  **dropped** (free plan locked to 2022–2024). See `tasks/todo.md §0` for the full pivot.
- **Persistence is stdlib sqlite3 + Pydantic**, deliberately no ORM; the whole state is one
  portable `.db` file. Datetimes are stored as ISO-8601 text and parsed back by Pydantic.
- **Bankroll/staking rules are constants in `config.py`** — change behavior there, not inline.
- **Tunable model IDs:** the LiteLLM strings in `PREDICTION_MODELS` are sensible defaults; they
  are expected to be edited as models change.

## Deployment

Develop on the Mac; run the live tournament on an always-on Linux home server. Git carries code
only; `.env` (real keys) and the `.db` (live state) live solely on the server. Deploy =
`git clone` → `uv sync` → create `.env` → run, scheduled via systemd timers / cron. All models
are reached through **OpenRouter** (one key, no local inference, no GPU); Pydantic AI points at
OpenRouter's OpenAI-compatible endpoint.
