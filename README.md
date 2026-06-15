# World Cup Agents

World Cup Agents is a simulated betting competition in which seven large language
models predict FIFA World Cup 2026 matches and manage virtual $1 million bankrolls.
Every model receives the same factual briefing, makes a football prediction without
seeing the market, and then decides whether to bet after the odds are revealed.

The project measures three different abilities:

- **Forecasting:** choosing the correct 90-minute result and exact score.
- **Probability judgment:** producing calibrated home/draw/away probabilities.
- **Bankroll management:** finding worthwhile prices without going broke.

The full competition rules and data-flow design are documented in
[`tasks/DESIGN.md`](tasks/DESIGN.md).

## How It Works

For each fixture, the pipeline:

1. Builds shared team dossiers from researched, time-appropriate facts.
2. Produces one factual match briefing for every competing model.
3. Asks each model for a blind 90-minute forecast with probabilities and reasoning.
4. Reveals consensus bookmaker odds and asks the model to bet or pass.
5. Records the result, settles bets, updates bankrolls, and folds the result into
   future dossiers.
6. Publishes predictions, reasoning, standings, and model telemetry through the Arena
   web application.

Predictions are settled on the score after 90 minutes plus stoppage time. Extra time
and penalties determine who advances in knockout matches, but do not change the 1X2
bet result.

## Architecture

```text
OpenFootball schedule ─┐
The Odds API ──────────┼─> SQLite <─> tournament pipeline
Web research / LLMs ───┘      │
                              ├─> FastAPI read-only API
                              └─> Next.js Arena
```

The scheduled orchestrator is intentionally idempotent. Each tick derives work from
fixture times and database state, then performs the following stages in order:

```text
results -> settlement -> post-match dossiers -> bracket resolution
        -> idle decay -> briefings -> late updates -> predictions and bets
```

This ordering prevents future information from leaking into earlier predictions.

## Technology

- Python 3.11
- Pydantic AI and OpenRouter
- SQLite
- FastAPI and Uvicorn
- Next.js 15, React 19, and TypeScript
- OpenFootball, API-Football, and The Odds API data
- `uv` for Python dependency and environment management

## Repository Layout

| Path | Purpose |
|---|---|
| `src/worldcup_agents/` | Tournament engine, models, persistence, and CLIs |
| `src/worldcup_agents/sources/` | Schedule, odds, naming, and geography adapters |
| `src/worldcup_agents/web/` | Read-only FastAPI application |
| `web/` | Next.js Arena frontend |
| `scripts/` | Offline verification, smoke-test, backup, and dry-run tools |
| `deploy/` | systemd units and installation scripts |
| `tasks/` | Design decisions, implementation notes, and acceptance criteria |

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/)
- Node.js 20 or newer for the Arena frontend
- API credentials described in [`.env.example`](.env.example)

## Local Setup

```bash
git clone https://github.com/thecr7guy2/worldcup-agents.git
cd worldcup-agents

uv sync
cp .env.example .env
```

Fill in the required values in `.env`:

| Variable | Used for |
|---|---|
| `API_FOOTBALL_KEY` | Football data access |
| `ODDS_API_KEY` | Consensus 1X2 prices |
| `OPENROUTER_API_KEY` | Intelligence and competitor model calls |

Optional challenger, external API, and visitor-geography settings are documented
inline in [`.env.example`](.env.example).

## Initialize the Tournament

Seed the 48 teams and 104 fixtures, capture an odds snapshot, and verify the imported
schedule:

```bash
uv run python -m worldcup_agents.ingest seed
uv run python -m worldcup_agents.ingest odds
uv run python -m worldcup_agents.ingest verify
```

These commands create and update `worldcup.db` in the repository root. The database
and `.env` are intentionally ignored by Git.

## Common Commands

Inspect work that is currently due without performing external calls:

```bash
uv run python -m worldcup_agents.orchestrate status
uv run python -m worldcup_agents.bracket status
```

Run one idempotent tournament pass:

```bash
uv run python -m worldcup_agents.orchestrate tick
```

Run a specific fixture's prediction and betting flow:

```bash
uv run python -m worldcup_agents.predict predict <fixture-id> --reasons
```

Inspect leaderboards:

```bash
uv run python -m worldcup_agents.leaderboard
uv run python -m worldcup_agents.leaderboard bankroll
uv run python -m worldcup_agents.leaderboard accuracy
uv run python -m worldcup_agents.leaderboard brier
```

Some commands perform paid LLM calls, web searches, or odds requests. Use the status
and verification commands when you only need a read-only check.

## Run the Arena Locally

The showcase uses two processes. From the repository root, start the API:

```bash
uv run uvicorn worldcup_agents.web.app:app --reload --port 8001
```

In another terminal, start the frontend:

```bash
cd web
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). The frontend proxies `/api/*`
requests to the FastAPI process. Set `WORLDCUP_DB=/absolute/path/to/worldcup.db` to
serve a database outside the repository root.

See [`web/README.md`](web/README.md) for routes and UI details.

## Verification

Run Python formatting and lint checks:

```bash
uv run black --check src scripts
uv run ruff check src scripts
```

Run the offline verification scripts:

```bash
for script in scripts/verify_*.py; do
  uv run python "$script"
done
```

Build the frontend:

```bash
cd web
npm ci
npm run build
```

The `dry_run*.py` and `test_openrouter.py` scripts make real provider calls and may
incur cost. They are intended for explicit end-to-end validation, not routine linting.

## Deployment

The live competition runs on an always-on Linux host with systemd timers for the
orchestrator and odds polling, plus long-running FastAPI and Next.js services.

Follow [`deploy/README.md`](deploy/README.md) for the complete server setup,
operations, backup, and update runbook.

## Data and Secret Safety

- Never commit `.env`, `web/.env.local`, or `worldcup.db`.
- Treat model and data-provider calls as potentially billable.
- Keep the API read-only; tournament mutations belong in the Python pipeline.
- Back up `worldcup.db` regularly because it contains the live competition state.
