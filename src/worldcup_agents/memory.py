"""Controlled memory for competitors.

The competitors do not get database tools. The engine retrieves memory deterministically
and injects bounded text into prompts:

* shared tournament memory: factual DB state, identical for every model;
* private self-memory: only that model's prior bets/results/penalties;
* constitution: the model's own self-written betting principles, public on its profile.

No block includes other agents' picks, reasoning, or stake choices.
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone

from . import db
from .config import PREDICTION_MODELS, ModelSpec
from .llm import LLMError, complete, extract_json
from .models import AgentConstitution, AgentMemory, Fixture, MatchStatus

_LEVELS = {"low", "medium", "high"}

SYSTEM_CONSTITUTION = """You are defining your own durable betting constitution for a \
virtual World Cup bankroll competition. Write principles that you can actually follow. \
Do not mention other agents. Do not ask to see private information. Be specific about \
football signals, price discipline, and bankroll risk."""


def _now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def _level(raw: object) -> str:
    """Normalize a model-provided low/medium/high field."""
    value = str(raw or "").strip().lower()
    return value if value in _LEVELS else "medium"


def _principles(raw: object) -> list[str]:
    """Normalize a model-provided principles list."""
    if not isinstance(raw, list):
        raise LLMError(f"constitution principles must be a list, got {raw!r}")
    out: list[str] = []
    for item in raw:
        text = " ".join(str(item).strip().split())
        if text and text not in out:
            out.append(text[:220])
    if len(out) < 4:
        raise LLMError(f"constitution needs at least 4 usable principles, got {raw!r}")
    return out[:10]


def ask_constitution(
    conn: sqlite3.Connection,
    model: ModelSpec,
    *,
    force: bool = False,
) -> AgentConstitution:
    """Ask one model to write its own durable betting constitution."""
    if not force:
        existing = db.get_agent_constitution(conn, model.name)
        if existing:
            return existing

    prompt = """You are one of seven AI football bettors in a public World Cup 2026 \
virtual-bankroll competition. You start with a $1,000,000 bankroll. You predict each match \
with odds hidden, then decide whether to back an eligible outcome after odds are revealed.

Write YOUR OWN betting constitution. This will be public on your agent page and will be \
shown back to you before future betting decisions. It should make your style distinct but \
not reckless or theatrical.

Return ONLY one valid JSON object:
{"principles": ["<6-10 concrete principles>"], \
"aggression": "low" | "medium" | "high", \
"favorite_tolerance": "low" | "medium" | "high", \
"draw_appetite": "low" | "medium" | "high", \
"contrarian_tendency": "low" | "medium" | "high", \
"bankroll_discipline": "low" | "medium" | "high", \
"constitution": "<6-10 sentences explaining your betting identity in first person>"}

Guidance:
- Say which football signals you trust most.
- Say when you will back short favorites, draws, and underdogs.
- Say how you change risk when your bankroll is ahead or behind.
- Say how you will avoid repeating mistakes.
- Do not mention other agents' private choices; you will not see them before betting."""

    text, call = complete(
        model.model_id,
        prompt,
        model_name=model.name,
        step="constitution",
        system=SYSTEM_CONSTITUTION,
        max_tokens=12000,
        temperature=0.6,
        reasoning_effort="medium",
    )
    db.log_model_call(conn, call)
    data = extract_json(text)
    constitution = " ".join(str(data.get("constitution", "")).strip().split())
    if not constitution:
        raise LLMError(f"{model.name}: missing constitution text in {data!r}")
    result = AgentConstitution(
        model_name=model.name,
        created_at=_now(),
        principles=_principles(data.get("principles")),
        aggression=_level(data.get("aggression")),
        favorite_tolerance=_level(data.get("favorite_tolerance")),
        draw_appetite=_level(data.get("draw_appetite")),
        contrarian_tendency=_level(data.get("contrarian_tendency")),
        bankroll_discipline=_level(data.get("bankroll_discipline")),
        constitution=constitution[:1600],
    )
    db.upsert_agent_constitution(conn, result)
    return result


def ask_all_constitutions(
    conn: sqlite3.Connection, *, force: bool = False
) -> tuple[list[AgentConstitution], list[str]]:
    """Ask every configured competitor for a constitution; collect per-model errors."""
    out: list[AgentConstitution] = []
    errors: list[str] = []
    for model in PREDICTION_MODELS:
        try:
            out.append(ask_constitution(conn, model, force=force))
        except Exception as e:  # noqa: BLE001 - report all failures
            errors.append(f"{model.name}: {type(e).__name__}: {e}")
    return out, errors


def _team_name(conn: sqlite3.Connection, team_id: int | None, label: str | None) -> str:
    """Resolve a team name for compact memory text."""
    if team_id is not None:
        team = db.get_team(conn, team_id)
        if team:
            return team.name
    return label or "TBD"


def _fixture_line(conn: sqlite3.Connection, fixture: Fixture) -> str:
    """Compact one-line fixture/result rendering."""
    home = _team_name(conn, fixture.home_id, fixture.home_label)
    away = _team_name(conn, fixture.away_id, fixture.away_label)
    date = fixture.kickoff.date().isoformat()
    if fixture.result_90() is not None:
        return (
            f"{date}: {home} {fixture.home_goals_90}-{fixture.away_goals_90} "
            f"{away} ({fixture.stage.value})"
        )
    return f"{date}: {home} vs {away} ({fixture.stage.value}, {fixture.status.value})"


def _team_record(conn: sqlite3.Connection, team_id: int) -> str:
    """Summarize one team's finished tournament record from authoritative fixtures."""
    fixtures = [
        f
        for f in db.list_fixtures(conn)
        if f.status == MatchStatus.FINISHED
        and f.result_90() is not None
        and team_id in {f.home_id, f.away_id}
    ]
    if not fixtures:
        return "no completed tournament matches yet"
    wins = draws = losses = gf = ga = 0
    recent: list[str] = []
    for f in sorted(fixtures, key=lambda x: x.kickoff):
        is_home = f.home_id == team_id
        own = f.home_goals_90 if is_home else f.away_goals_90
        opp = f.away_goals_90 if is_home else f.home_goals_90
        assert own is not None and opp is not None
        gf += own
        ga += opp
        if own > opp:
            wins += 1
            mark = "W"
        elif own < opp:
            losses += 1
            mark = "L"
        else:
            draws += 1
            mark = "D"
        opponent = _team_name(conn, f.away_id if is_home else f.home_id, None)
        recent.append(f"{mark} {own}-{opp} vs {opponent}")
    pts = wins * 3 + draws
    return f"{wins}-{draws}-{losses}, {gf}-{ga} goals, {pts} pts; recent: {'; '.join(recent[-4:])}"


def shared_tournament_memory(conn: sqlite3.Connection, fixture: Fixture | None) -> str:
    """Build a factual tournament-state packet, identical for every competitor."""
    lines = ["## Shared Tournament Memory", "Authoritative DB facts only; no odds and no agent bets."]
    if fixture and fixture.home_id and fixture.away_id:
        home = _team_name(conn, fixture.home_id, fixture.home_label)
        away = _team_name(conn, fixture.away_id, fixture.away_label)
        lines.append(f"- {home} tournament record: {_team_record(conn, fixture.home_id)}.")
        lines.append(f"- {away} tournament record: {_team_record(conn, fixture.away_id)}.")

    finished = [
        f
        for f in db.list_fixtures(conn)
        if f.status == MatchStatus.FINISHED and f.result_90() is not None
    ]
    if finished:
        lines.append("- Recent tournament results:")
        for f in sorted(finished, key=lambda x: x.kickoff)[-8:]:
            lines.append(f"  - {_fixture_line(conn, f)}")
    else:
        lines.append("- No tournament matches have finished yet.")
    return "\n".join(lines)


def refresh_agent_memory(conn: sqlite3.Connection, model_name: str) -> AgentMemory:
    """Update one model's private self-memory from its own rows only."""
    comp = db.get_competitor(conn, model_name)
    bets = conn.execute(
        "SELECT pick, stake FROM bet WHERE model_name = ?", (model_name,)
    ).fetchall()
    settlements = conn.execute(
        "SELECT fixture_id, result, pnl FROM settlement WHERE model_name = ? "
        "ORDER BY settled_at DESC LIMIT 8",
        (model_name,),
    ).fetchall()
    ledger = db.list_bankroll_history(conn, model_name)
    active_bets = [b for b in bets if b["pick"] is not None and (b["stake"] or 0) > 0]
    passes = len(bets) - len(active_bets)
    total_staked = sum((b["stake"] or 0) for b in active_bets)
    avg_stake = total_staked / len(active_bets) if active_bets else 0.0
    decay_hits = [e for e in ledger if e.reason == "portfolio_decay"]

    lines = ["Private self-memory. Only your own history is included; no competitor picks."]
    if comp:
        lines.append(
            f"- Current bankroll: ${comp.bankroll:,.0f}; profit/loss from start: "
            f"${comp.bankroll - 1_000_000:,.0f}; active={comp.active}."
        )
    lines.append(
        f"- Betting activity: {len(active_bets)} real bets, {passes} passes, "
        f"average real stake ${avg_stake:,.0f}."
    )
    if decay_hits:
        lines.append(
            f"- You have paid {len(decay_hits)} matchday portfolio shortfall penalties; "
            "do not let playable slates drift into cash by default."
        )
    if settlements:
        lines.append("- Recent settled outcomes:")
        for s in settlements:
            fx = db.get_fixture(conn, s["fixture_id"])
            label = _fixture_line(conn, fx) if fx else f"fixture {s['fixture_id']}"
            lines.append(f"  - {label}: {s['result']}, P&L ${s['pnl'] or 0:,.0f}")
    else:
        lines.append("- No settled bets yet; use the constitution rather than past results.")

    memory = AgentMemory(
        model_name=model_name,
        updated_at=_now(),
        content="\n".join(lines),
    )
    db.upsert_agent_memory(conn, memory)
    return memory


def private_memory_block(conn: sqlite3.Connection, model_name: str) -> str:
    """Return a private self-memory prompt block, refreshing if missing."""
    memory = db.get_agent_memory(conn, model_name) or refresh_agent_memory(
        conn, model_name
    )
    return f"## Your Private Self-Memory\n{memory.content}"


def constitution_block(conn: sqlite3.Connection, model_name: str) -> str:
    """Return the model's constitution as a prompt block, or a neutral fallback."""
    c = db.get_agent_constitution(conn, model_name)
    if c is None:
        return (
            "## Your Betting Constitution\n"
            "No self-written constitution has been recorded yet. Use disciplined football "
            "judgment, the matchday portfolio target, and meaningful bankroll risk."
        )
    principles = "\n".join(f"- {p}" for p in c.principles)
    return (
        "## Your Betting Constitution\n"
        f"Profile: aggression={c.aggression}, favorite_tolerance={c.favorite_tolerance}, "
        f"draw_appetite={c.draw_appetite}, contrarian_tendency={c.contrarian_tendency}, "
        f"bankroll_discipline={c.bankroll_discipline}.\n"
        f"{principles}\n\n{c.constitution}"
    )


def betting_memory_block(
    conn: sqlite3.Connection, model_name: str, fixture: Fixture
) -> str:
    """Private memory bundle injected only into the bet step."""
    return "\n\n".join(
        [
            shared_tournament_memory(conn, fixture),
            constitution_block(conn, model_name),
            private_memory_block(conn, model_name),
        ]
    )


def format_constitution(c: AgentConstitution) -> str:
    """Render one constitution as Markdown for CLI output."""
    principles = "\n".join(f"- {p}" for p in c.principles)
    return (
        f"## {c.model_name}\n"
        f"aggression={c.aggression} · favorites={c.favorite_tolerance} · "
        f"draws={c.draw_appetite} · contrarian={c.contrarian_tendency} · "
        f"discipline={c.bankroll_discipline}\n\n"
        f"{principles}\n\n{c.constitution}\n"
    )


def _cmd_constitution(args: argparse.Namespace) -> None:
    """Ask/show constitutions for all competitors."""
    conn = db.connect()
    db.init_db(conn)
    if args.action == "ask":
        constitutions, errors = ask_all_constitutions(conn, force=args.force)
        for c in constitutions:
            print(format_constitution(c))
        if errors:
            print(f"Failed ({len(errors)}):")
            for err in errors:
                print(f"  ERROR {err}")
            raise SystemExit(1)
    else:
        constitutions = db.list_agent_constitutions(conn)
        if not constitutions:
            print("(no constitutions recorded)")
        for c in constitutions:
            print(format_constitution(c))


def _cmd_refresh(args: argparse.Namespace) -> None:
    """Refresh deterministic private self-memory for every competitor."""
    conn = db.connect()
    db.init_db(conn)
    models = [m.name for m in PREDICTION_MODELS] if args.model is None else [args.model]
    for model_name in models:
        memory = refresh_agent_memory(conn, model_name)
        print(f"## {memory.model_name} ({memory.updated_at:%Y-%m-%d %H:%MZ})")
        print(memory.content)
        print()


def main() -> None:
    """Parse and dispatch memory commands."""
    parser = argparse.ArgumentParser(prog="worldcup_agents.memory")
    sub = parser.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("constitution", help="ask/show self-written constitutions")
    c.add_argument("action", choices=("ask", "show"))
    c.add_argument("--force", action="store_true", help="re-ask even if recorded")
    c.set_defaults(func=_cmd_constitution)

    r = sub.add_parser("refresh", help="refresh private self-memory")
    r.add_argument("--model", default=None, help="one model name; default all")
    r.set_defaults(func=_cmd_refresh)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
