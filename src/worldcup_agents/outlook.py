"""Tournament outlook interviews — each competitor's worldview, captured per phase.

Before the opening match (and again at later phases) every prediction model is asked,
with NO briefing, NO odds, and NO web access, for its tournament-level convictions:
champion, finalists, semifinalists, dark horses, golden boot, and a short worldview.

Why this exists (report material, not competition machinery):

* **Priors.** The per-match pipeline only ever shows a model two teams at a time; this
  captures the prior worldview it brings into the tournament — which the report can
  correlate with its betting behaviour (does a model that crowns Brazil in June keep
  paying for that belief in July?).
* **Belief revision.** Re-asking the SAME questions at later phases ("post_group",
  "pre_final", "post_final") measures how each model updates under evidence — stubborn
  vs. reactive is a per-model trait the report can chart.
* **Grading.** Phases asked before the bracket resolves are gradeable foresight
  (champion named on day 0 is worth more than champion named at the semis).

Isolation: outlooks are write-only report data. They are never fed into predictions,
bets, briefings, or dossiers — every prediction call stays stateless (DESIGN §2).

CLI:
    uv run python -m worldcup_agents.outlook ask --phase pre     # all models, idempotent
    uv run python -m worldcup_agents.outlook show [--phase pre]
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone

from . import db
from .config import PREDICTION_MODELS, ModelSpec
from .llm import LLMError, complete, extract_json
from .models import TournamentOutlook
from .predict import SYSTEM_FORECASTER

PHASES = ("pre", "post_group", "pre_final", "post_final")

_PROMPT = """The FIFA World Cup 2026 (48 teams, North America) {timeframe}.

Using ONLY your own knowledge — you have no briefing and no live data — state your \
honest tournament-level convictions. This is asked at phase "{phase}".

Respond with ONLY a JSON object, no other text:
{{"champion": "<team you believe lifts the trophy>", \
"runner_up": "<beaten finalist>", \
"semifinalists": ["<team>", "<team>", "<team>", "<team>"], \
"dark_horses": ["<2-3 teams that will overperform expectations>"], \
"golden_boot": "<player you expect to finish top scorer>", \
"worldview": "<4-8 sentences: how you see this tournament playing out — the \
contenders' relative strengths, the biggest risks to the favourites, and what you \
expect to matter most (conditions, squad depth, form)>"}}
semifinalists must include champion and runner_up. Be decisive — name real teams and \
a real player."""

_TIMEFRAMES = {
    "pre": "is about to begin",
    "post_group": "has finished its group stage",
    "pre_final": "is about to play its final",
    "post_final": "has concluded",
}


def _now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def _parse_team_list(raw: object, *, want: int | None = None) -> list[str]:
    """Validate and normalize a model-provided list of team names."""
    if not isinstance(raw, list):
        raise LLMError(f"expected a list of teams, got {raw!r}")
    teams = [" ".join(str(t).strip().split()) for t in raw if str(t).strip()]
    if not teams or (want is not None and len(teams) != want):
        raise LLMError(f"expected {want or 'some'} teams, got {raw!r}")
    return teams


def ask_outlook(
    conn: sqlite3.Connection,
    model: ModelSpec,
    *,
    phase: str = "pre",
    force: bool = False,
) -> TournamentOutlook:
    """Ask one model for its tournament outlook at a phase (idempotent per phase)."""
    if phase not in PHASES:
        raise ValueError(f"phase must be one of {PHASES}, got {phase!r}")
    if not force:
        existing = db.get_outlook(conn, model.name, phase)
        if existing:
            return existing

    prompt = _PROMPT.format(phase=phase, timeframe=_TIMEFRAMES[phase])
    text, call = complete(
        model.model_id,
        prompt,
        model_name=model.name,
        step="outlook",
        system=SYSTEM_FORECASTER,
        max_tokens=25000,  # generous — let reasoning models think freely, never capped
        temperature=0.5,
        reasoning_effort="high",
    )
    db.log_model_call(conn, call)

    data = extract_json(text)
    champion = str(data.get("champion", "")).strip()
    runner_up = str(data.get("runner_up", "")).strip()
    golden_boot = str(data.get("golden_boot", "")).strip()
    worldview = str(data.get("worldview", "")).strip()
    if not (champion and runner_up and golden_boot and worldview):
        raise LLMError(f"{model.name}: incomplete outlook in {data!r}")

    outlook = TournamentOutlook(
        model_name=model.name,
        phase=phase,
        asked_at=_now(),
        champion=champion,
        runner_up=runner_up,
        semifinalists=_parse_team_list(data.get("semifinalists"), want=4),
        dark_horses=_parse_team_list(data.get("dark_horses")),
        golden_boot=golden_boot,
        worldview=worldview,
    )
    db.upsert_outlook(conn, outlook)
    return outlook


def ask_all(
    conn: sqlite3.Connection, *, phase: str = "pre", force: bool = False
) -> tuple[list[TournamentOutlook], list[str]]:
    """Ask every competitor (sequentially — a handful of calls, no rush). Per-model
    failures are collected, never fatal, so one flaky model can't block the others."""
    outlooks: list[TournamentOutlook] = []
    errors: list[str] = []
    for model in PREDICTION_MODELS:
        try:
            outlooks.append(ask_outlook(conn, model, phase=phase, force=force))
        except Exception as e:  # noqa: BLE001 - collect and continue
            errors.append(f"{model.name}: {type(e).__name__}: {e}")
    return outlooks, errors


def format_outlook(o: TournamentOutlook) -> str:
    """Render one recorded tournament outlook as Markdown."""
    semis = ", ".join(o.semifinalists)
    horses = ", ".join(o.dark_horses)
    return (
        f"## {o.model_name} ({o.phase}, {o.asked_at:%Y-%m-%d})\n"
        f"**Champion:** {o.champion} · **Runner-up:** {o.runner_up}\n"
        f"**Semifinalists:** {semis}\n"
        f"**Dark horses:** {horses} · **Golden boot:** {o.golden_boot}\n\n"
        f"{o.worldview}\n"
    )


# ---- CLI -----------------------------------------------------------------


def _cmd_ask(args: argparse.Namespace) -> None:
    """Run the outlook interview for every configured competitor."""
    conn = db.connect()
    db.init_db(conn)
    outlooks, errors = ask_all(conn, phase=args.phase, force=args.force)
    for o in outlooks:
        print(format_outlook(o))
    if errors:
        print(f"Failed ({len(errors)}):")
        for err in errors:
            print(f"  ERROR {err}")
        raise SystemExit(1)


def _cmd_show(args: argparse.Namespace) -> None:
    """Print previously recorded outlook interviews."""
    conn = db.connect()
    db.init_db(conn)
    outlooks = db.list_outlooks(conn, phase=args.phase)
    if not outlooks:
        print("(no outlooks recorded)")
        return
    for o in outlooks:
        print(format_outlook(o))


def main() -> None:
    """Parse and dispatch the tournament-outlook command-line interface."""
    parser = argparse.ArgumentParser(prog="worldcup_agents.outlook")
    sub = parser.add_subparsers(dest="cmd", required=True)

    ask = sub.add_parser(
        "ask", help="interview every competitor (idempotent per phase)"
    )
    ask.add_argument("--phase", choices=PHASES, default="pre")
    ask.add_argument("--force", action="store_true", help="re-ask even if recorded")
    ask.set_defaults(func=_cmd_ask)

    show = sub.add_parser("show", help="print recorded outlooks")
    show.add_argument("--phase", choices=PHASES, default=None)
    show.set_defaults(func=_cmd_show)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
