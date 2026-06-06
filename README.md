# World Cup Agents

A competition where 5 LLMs act as **virtual gamblers** predicting FIFA World Cup 2026
matches. A single intelligence agent gathers facts into shared, per-team dossiers; each
model reasons over the *same* information and bets a $1M virtual bankroll on the match
winner. We measure who reasons best under uncertainty.

Full design: [`tasks/DESIGN.md`](tasks/DESIGN.md).

## Setup

```bash
uv sync                 # create venv + install deps
cp .env.example .env    # then fill in your API keys
```

Required keys (see `.env.example`): `API_FOOTBALL_KEY`, `ODDS_API_KEY`, and
`OPENROUTER_API_KEY` (all 5 models route through OpenRouter).

## Stack

Python 3.11 · Pydantic AI · OpenRouter (all models, one key) · SQLite · data from
API-Football + The Odds API.
