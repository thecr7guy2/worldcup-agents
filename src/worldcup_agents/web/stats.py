"""Serialization + derived stats for the API.

Pure read views over competition state. Domain logic (accuracy scoring, bankroll order,
the 1X2-on-90' rule) is reused from leaderboard.py / db.py / models.py rather than
re-implemented, so the site can never drift from the engine that runs the competition.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .. import db, leaderboard
from ..config import MAX_LIVES, MAX_STAKE_FRACTION, STARTING_BANKROLL
from ..models import Competitor, Fixture, MatchStatus, Team
from . import agents_meta
from .flags import code_for, iso_for


# ---- small helpers -------------------------------------------------------


def _team_index(conn: sqlite3.Connection) -> dict[int, Team]:
    """All teams keyed by id (one query, reused across a request)."""
    rows = conn.execute(
        'SELECT id, name, code, "group", fifa_rank FROM team'
    ).fetchall()
    return {r["id"]: Team(**dict(r)) for r in rows}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def team_side(team: Team | None, label: str | None) -> dict:
    """Serialize one side of a fixture: a resolved team, or an unresolved bracket slot."""
    if team is not None:
        return {
            "resolved": True,
            "id": team.id,
            "name": team.name,
            "code": code_for(team.name),
            "iso": iso_for(team.name),
            "group": team.group,
            "fifa_rank": team.fifa_rank,
        }
    return {
        "resolved": False,
        "id": None,
        "name": label or "TBD",
        "code": None,
        "iso": None,
        "group": None,
        "fifa_rank": None,
    }


# ---- fixtures ------------------------------------------------------------


def serialize_fixture(
    fx: Fixture, teams: dict[int, Team], odds: dict | None
) -> dict:
    """A fixture flattened for the UI: both sides resolved, odds + result attached."""
    home = team_side(teams.get(fx.home_id) if fx.home_id else None, fx.home_label)
    away = team_side(teams.get(fx.away_id) if fx.away_id else None, fx.away_label)

    result = None
    if fx.home_goals_90 is not None and fx.away_goals_90 is not None:
        outcome = fx.result_90()
        result = {
            "home_goals": fx.home_goals_90,
            "away_goals": fx.away_goals_90,
            "outcome": outcome.value if outcome else None,
            "went_extra_time": fx.went_extra_time,
            "went_penalties": fx.went_penalties,
            "advanced_id": fx.advanced_id,
        }

    return {
        "id": fx.id,
        "stage": fx.stage.value,
        "group": fx.group,
        "kickoff": fx.kickoff.isoformat(),
        "venue": fx.venue,
        "status": fx.status.value,
        "home": home,
        "away": away,
        "odds": odds,
        "result": result,
    }


def _consensus_odds_dict(conn: sqlite3.Connection, fixture_id: int) -> dict | None:
    snap = db.consensus_odds(conn, fixture_id)
    if snap is None:
        return None
    return {
        "home": snap.home,
        "draw": snap.draw,
        "away": snap.away,
        "bookmaker": snap.bookmaker,
        "captured_at": snap.captured_at.isoformat(),
    }


def list_fixtures(
    conn: sqlite3.Connection, *, day: str | None = None, stage: str | None = None
) -> list[dict]:
    """Serialized fixtures, optionally filtered by UTC date (YYYY-MM-DD) or stage."""
    teams = _team_index(conn)
    fixtures = db.list_fixtures(conn)
    out: list[dict] = []
    for fx in fixtures:
        if stage and fx.stage.value != stage:
            continue
        if day and fx.kickoff.astimezone(timezone.utc).date().isoformat() != day:
            continue
        out.append(serialize_fixture(fx, teams, _consensus_odds_dict(conn, fx.id)))
    return out


def fixture_detail(conn: sqlite3.Connection, fixture_id: int) -> dict | None:
    """One fixture plus every agent's prediction -> bet -> settlement for it."""
    fx = db.get_fixture(conn, fixture_id)
    if fx is None:
        return None
    teams = _team_index(conn)
    base = serialize_fixture(fx, teams, _consensus_odds_dict(conn, fixture_id))
    base["briefed"] = db.get_match_briefing(conn, fixture_id) is not None

    # Per-model board: prediction (step 1), bet (step 2), settlement.
    preds = {
        r["model_name"]: dict(r)
        for r in conn.execute(
            "SELECT model_name, winner, pred_home_goals, pred_away_goals, "
            "predicted_advance, confidence, reasoning FROM prediction WHERE fixture_id = ?",
            (fixture_id,),
        )
    }
    bets = {
        r["model_name"]: dict(r)
        for r in conn.execute(
            "SELECT model_name, pick, stake, odds_at_bet, reasoning "
            "FROM bet WHERE fixture_id = ?",
            (fixture_id,),
        )
    }
    setts = {
        r["model_name"]: dict(r)
        for r in conn.execute(
            "SELECT model_name, result, payout, pnl FROM settlement WHERE fixture_id = ?",
            (fixture_id,),
        )
    }

    board = []
    for c in db.list_competitors(conn):
        m = c.model_name
        board.append(
            {
                "model": m,
                "meta": agents_meta.meta_for(m),
                "prediction": preds.get(m),
                "bet": bets.get(m),
                "settlement": setts.get(m),
            }
        )
    base["board"] = board
    return base


# ---- competitors ("characters") -----------------------------------------


def _streak(settled: list[dict]) -> dict:
    """Current win/loss streak from settlements (newest first already filtered)."""
    streak_type, count = None, 0
    for s in settled:
        r = s["result"]
        if r not in ("win", "loss"):
            continue
        if streak_type is None:
            streak_type, count = r, 1
        elif r == streak_type:
            count += 1
        else:
            break
    return {"type": streak_type, "count": count}


def _archetype(
    *, bets_placed: int, passes: int, avg_stake_pct: float, hit_rate: float, roi: float
) -> str:
    """A flavor class derived from staking behavior. Heuristic, for the character sheet."""
    if bets_placed == 0:
        return "Rookie"
    total_decisions = bets_placed + passes
    pass_rate = passes / total_decisions if total_decisions else 0.0
    aggressive = avg_stake_pct > 0.5 * MAX_STAKE_FRACTION  # >12.5% of bankroll
    accurate = hit_rate >= 0.55
    profitable = roi > 0
    if accurate and profitable:
        return "Sharpshooter"
    if aggressive and profitable:
        return "High Roller"
    if aggressive and not profitable:
        return "Daredevil"
    if pass_rate > 0.4:
        return "Tactician"
    if profitable:
        return "Grinder"
    return "Underdog"


def competitor_card(
    conn: sqlite3.Connection,
    c: Competitor,
    accuracy_by_model: dict[str, dict],
    usage_by_model: dict[str, dict],
) -> dict:
    """A competitor's full character sheet: standing + computed performance + telemetry."""
    bets = conn.execute(
        "SELECT pick, stake FROM bet WHERE model_name = ?", (c.model_name,)
    ).fetchall()
    settled = [
        dict(r)
        for r in conn.execute(
            "SELECT result, pnl, fixture_id FROM settlement WHERE model_name = ? "
            "ORDER BY settled_at DESC",
            (c.model_name,),
        )
    ]

    active_bets = [b for b in bets if b["pick"] is not None and (b["stake"] or 0) > 0]
    passes = len(bets) - len(active_bets)
    total_staked = sum((b["stake"] or 0) for b in active_bets)
    avg_stake = total_staked / len(active_bets) if active_bets else 0.0
    avg_stake_pct = avg_stake / STARTING_BANKROLL if active_bets else 0.0

    wins = sum(1 for s in settled if s["result"] == "win")
    losses = sum(1 for s in settled if s["result"] == "loss")
    voids = sum(1 for s in settled if s["result"] == "void")
    decided = wins + losses
    win_rate = wins / decided if decided else 0.0
    net_pnl = sum((s["pnl"] or 0) for s in settled)
    roi = net_pnl / total_staked if total_staked > 0 else 0.0

    acc = accuracy_by_model.get(c.model_name, {})
    usage = usage_by_model.get(c.model_name, {})
    hit_rate = float(acc.get("hit_rate", 0.0) or 0.0)

    return {
        "model": c.model_name,
        "meta": agents_meta.meta_for(c.model_name),
        # standing
        "bankroll": c.bankroll,
        "starting_bankroll": STARTING_BANKROLL,
        "profit": c.bankroll - STARTING_BANKROLL,
        "active": c.active,
        "lives_used": c.lives_used,
        "max_lives": MAX_LIVES,
        # betting performance
        "bets_placed": len(active_bets),
        "passes": passes,
        "total_staked": total_staked,
        "avg_stake": avg_stake,
        "avg_stake_pct": avg_stake_pct,
        "wins": wins,
        "losses": losses,
        "voids": voids,
        "win_rate": win_rate,
        "net_pnl": net_pnl,
        "roi": roi,
        "streak": _streak(settled),
        # prediction accuracy (graded off step 1)
        "accuracy": {
            "points": acc.get("points", 0),
            "exact": acc.get("exact", 0),
            "outcomes": acc.get("outcomes", 0),
            "advance": acc.get("advance", 0),
            "graded": acc.get("total", 0),
            "hit_rate": hit_rate,
        },
        # telemetry
        "telemetry": {
            "calls": usage.get("calls", 0) or 0,
            "tokens": usage.get("tokens", 0) or 0,
            "cost_usd": usage.get("cost_usd", 0.0) or 0.0,
        },
        "archetype": _archetype(
            bets_placed=len(active_bets),
            passes=passes,
            avg_stake_pct=avg_stake_pct,
            hit_rate=hit_rate,
            roi=roi,
        ),
    }


def _accuracy_index(conn: sqlite3.Connection) -> dict[str, dict]:
    return {row["model"]: row for row in leaderboard.accuracy_standings(conn)}


def _usage_index(conn: sqlite3.Connection) -> dict[str, dict]:
    return {row["model_name"]: row for row in db.usage_by_model(conn)}


def list_competitors(conn: sqlite3.Connection) -> list[dict]:
    """Every competitor's character sheet, in bankroll order."""
    acc = _accuracy_index(conn)
    usage = _usage_index(conn)
    return [
        competitor_card(conn, c, acc, usage)
        for c in db.list_competitors(conn)
    ]


def competitor_detail(conn: sqlite3.Connection, model_name: str) -> dict | None:
    """One character sheet plus bankroll history and a recent bet/prediction log."""
    c = db.get_competitor(conn, model_name)
    if c is None:
        return None
    card = competitor_card(conn, c, _accuracy_index(conn), _usage_index(conn))

    history = [
        {
            "at": e.at.isoformat(),
            "delta": e.delta,
            "balance_after": e.balance_after,
            "reason": e.reason,
            "fixture_id": e.fixture_id,
        }
        for e in db.list_bankroll_history(conn, model_name)
    ]

    # Recent activity: bet joined with its fixture + settlement, newest kickoff first.
    teams = _team_index(conn)
    log = []
    rows = conn.execute(
        "SELECT b.fixture_id, b.pick, b.stake, b.odds_at_bet, b.reasoning, "
        "       s.result, s.pnl "
        "FROM bet b LEFT JOIN settlement s "
        "  ON s.model_name = b.model_name AND s.fixture_id = b.fixture_id "
        "WHERE b.model_name = ? ORDER BY b.created_at DESC",
        (model_name,),
    ).fetchall()
    for r in rows:
        fx = db.get_fixture(conn, r["fixture_id"])
        fx_label = None
        if fx:
            h = team_side(teams.get(fx.home_id) if fx.home_id else None, fx.home_label)
            a = team_side(teams.get(fx.away_id) if fx.away_id else None, fx.away_label)
            fx_label = {"home": h, "away": a, "stage": fx.stage.value,
                        "kickoff": fx.kickoff.isoformat()}
        log.append(
            {
                "fixture_id": r["fixture_id"],
                "fixture": fx_label,
                "pick": r["pick"],
                "stake": r["stake"],
                "odds_at_bet": r["odds_at_bet"],
                "reasoning": r["reasoning"],
                "result": r["result"],
                "pnl": r["pnl"],
            }
        )

    card["bankroll_history"] = history
    card["log"] = log
    return card


# ---- leaderboards --------------------------------------------------------


def leaderboard_bankroll(conn: sqlite3.Connection) -> list[dict]:
    """Primary board: bankroll order, with the same derived stats as the roster."""
    return list_competitors(conn)  # already bankroll-ordered + fully enriched


def leaderboard_accuracy(conn: sqlite3.Connection) -> list[dict]:
    """Secondary board: accuracy points (stakes ignored), with agent metadata attached."""
    rows = leaderboard.accuracy_standings(conn)
    for r in rows:
        r["meta"] = agents_meta.meta_for(r["model"])
    return rows


# ---- telemetry -----------------------------------------------------------


def telemetry(conn: sqlite3.Connection) -> dict:
    """Tokens + cost per model, per step, and cost-per-correct-prediction."""
    by_model = db.usage_by_model(conn)
    acc = _accuracy_index(conn)
    for row in by_model:
        row["meta"] = agents_meta.meta_for(row["model_name"])
        outcomes = acc.get(row["model_name"], {}).get("outcomes", 0)
        cost = row.get("cost_usd", 0.0) or 0.0
        row["cost_per_correct"] = (cost / outcomes) if outcomes else None

    by_step = [
        dict(r)
        for r in conn.execute(
            "SELECT model_name, step, COUNT(*) AS calls, "
            "  SUM(total_tokens) AS tokens, SUM(cost_usd) AS cost_usd "
            "FROM model_call GROUP BY model_name, step ORDER BY model_name, step"
        )
    ]

    totals = conn.execute(
        "SELECT COUNT(*) AS calls, COALESCE(SUM(total_tokens),0) AS tokens, "
        "COALESCE(SUM(cost_usd),0) AS cost_usd FROM model_call"
    ).fetchone()

    return {
        "by_model": by_model,
        "by_step": by_step,
        "totals": dict(totals),
    }


# ---- overview ------------------------------------------------------------


def overview(conn: sqlite3.Connection) -> dict:
    """Headline competition summary for the home page."""
    fixtures = db.list_fixtures(conn)
    status_spread: dict[str, int] = {}
    for fx in fixtures:
        status_spread[fx.status.value] = status_spread.get(fx.status.value, 0) + 1

    kickoffs = sorted(fx.kickoff for fx in fixtures)
    first_kick = kickoffs[0] if kickoffs else None
    last_kick = kickoffs[-1] if kickoffs else None

    now = _now_utc()
    upcoming = [fx for fx in fixtures if fx.kickoff >= now and fx.status == MatchStatus.SCHEDULED]
    upcoming.sort(key=lambda fx: fx.kickoff)
    teams = _team_index(conn)
    next_fx = (
        serialize_fixture(upcoming[0], teams, _consensus_odds_dict(conn, upcoming[0].id))
        if upcoming
        else None
    )

    bet_totals = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(stake),0) AS staked FROM bet "
        "WHERE pick IS NOT NULL AND stake > 0"
    ).fetchone()
    usage_totals = conn.execute(
        "SELECT COUNT(*) AS calls, COALESCE(SUM(total_tokens),0) AS tokens, "
        "COALESCE(SUM(cost_usd),0) AS cost_usd FROM model_call"
    ).fetchone()
    n_predictions = conn.execute("SELECT COUNT(*) FROM prediction").fetchone()[0]
    n_competitors = conn.execute(
        "SELECT COUNT(*) FROM competitor WHERE active = 1"
    ).fetchone()[0]
    total_bankroll = conn.execute(
        "SELECT COALESCE(SUM(bankroll),0) FROM competitor"
    ).fetchone()[0]

    days_to_kickoff = None
    if first_kick is not None and first_kick > now:
        days_to_kickoff = (first_kick - now).days
    started = any(fx.status != MatchStatus.SCHEDULED for fx in fixtures)

    return {
        "competitors": n_competitors,
        "total_bankroll": total_bankroll,
        "starting_bankroll": STARTING_BANKROLL,
        "fixtures_total": len(fixtures),
        "status_spread": status_spread,
        "first_kickoff": first_kick.isoformat() if first_kick else None,
        "last_kickoff": last_kick.isoformat() if last_kick else None,
        "days_to_kickoff": days_to_kickoff,
        "started": started,
        "next_fixture": next_fx,
        "totals": {
            "bets": bet_totals["n"],
            "staked": bet_totals["staked"],
            "predictions": n_predictions,
            "calls": usage_totals["calls"],
            "tokens": usage_totals["tokens"],
            "cost_usd": usage_totals["cost_usd"],
        },
    }
