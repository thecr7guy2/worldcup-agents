"""Serialization + derived stats for the API.

Pure read views over competition state. Domain logic (accuracy scoring, bankroll order,
the 1X2-on-90' rule) is reused from leaderboard.py / db.py / models.py rather than
re-implemented, so the site can never drift from the engine that runs the competition.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .. import db, leaderboard
from ..config import (
    BET_ELIGIBILITY_WINDOW,
    CHALLENGER_PUBLIC,
    MATCHDAY_SHORTFALL_PENALTY_FRACTION,
    MAX_LIVES,
    MAX_STAKE_FRACTION,
    STARTING_BANKROLL,
    stage_matchday_target_fraction,
    stage_stake_tiers,
)
from ..llm import LLMError, extract_json
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
    """Return the current timezone-aware UTC timestamp."""
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


def serialize_fixture(fx: Fixture, teams: dict[int, Team], odds: dict | None) -> dict:
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
    """Serialize the latest consensus odds snapshot for one fixture."""
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
    # The match briefing is the neutral, odds-free dossier every model reads. Surface its
    # markdown to the site (safe to show whenever it exists — no odds, no lean), and keep the
    # `briefed` flag derived from the same fetch so the two never disagree.
    mb = db.get_match_briefing(conn, fixture_id)
    base["briefed"] = mb is not None
    base["briefing"] = mb.content if mb else None

    # Per-model board: prediction (step 1), bet (step 2), settlement.
    preds = {
        r["model_name"]: dict(r)
        for r in conn.execute(
            "SELECT model_name, winner, p_home, p_draw, p_away, "
            "pred_home_goals, pred_away_goals, exp_home_goals, exp_away_goals, "
            "predicted_advance, confidence, reasoning FROM prediction WHERE fixture_id = ?",
            (fixture_id,),
        )
    }
    bets = {
        r["model_name"]: dict(r)
        for r in conn.execute(
            "SELECT model_name, pick, stake, odds_at_bet, p_revised, "
            "p_home_revised, p_draw_revised, p_away_revised, "
            "requested_pick, requested_stake, engine_adjustment, reasoning "
            "FROM bet WHERE fixture_id = ?",
            (fixture_id,),
        )
    }
    bet_responses = {
        r["model_name"]: r["response_text"]
        for r in conn.execute(
            "SELECT model_name, response_text FROM model_call "
            "WHERE fixture_id = ? AND step = 'bet' ORDER BY created_at",
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
                "decision_receipt": _decision_receipt(
                    fx,
                    preds.get(m),
                    bets.get(m),
                    _consensus_odds_dict(conn, fixture_id),
                    bet_responses.get(m),
                ),
            }
        )
    base["board"] = board
    return base


def _probabilities(prediction: dict | None) -> dict[str, float]:
    """Return finite 1X2 probabilities from a prediction row."""
    if prediction is None:
        return {}
    out = {}
    for key, outcome in (("p_home", "home"), ("p_draw", "draw"), ("p_away", "away")):
        value = prediction.get(key)
        if isinstance(value, int | float):
            out[outcome] = float(value)
    return out


def _chosen_stake_pct(response_text: str | None) -> float | None:
    """Read the model's requested stake_pct from the stored raw bet JSON."""
    if not response_text:
        return None
    try:
        data = extract_json(response_text)
    except LLMError:
        return None
    try:
        return float(data.get("stake_pct"))
    except (TypeError, ValueError):
        return None


def _market_implied(odds: dict | None) -> dict[str, float] | None:
    """Raw decimal-odds implied probabilities, not vig-normalized."""
    if odds is None:
        return None
    try:
        return {
            "home": 1.0 / float(odds["home"]),
            "draw": 1.0 / float(odds["draw"]),
            "away": 1.0 / float(odds["away"]),
        }
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def _decision_receipt(
    fixture: Fixture,
    prediction: dict | None,
    bet: dict | None,
    odds: dict | None,
    bet_response_text: str | None,
) -> dict | None:
    """Explain the mechanical inputs behind one agent's bet decision.

    This is deliberately derived from persisted rows rather than model memory: it tells the
    public what the engine actually showed/enforced for this fixture.
    """
    if prediction is None:
        return None
    probs = _probabilities(prediction)
    eligible: list[str] = []
    if probs:
        top = max(probs.values())
        eligible = [
            outcome
            for outcome, probability in probs.items()
            if top - probability <= BET_ELIGIBILITY_WINDOW + 1e-12
        ]

    chosen_pct = _chosen_stake_pct(bet_response_text)
    target = stage_matchday_target_fraction(fixture.stage.value)
    shortfall_penalty = target * MATCHDAY_SHORTFALL_PENALTY_FRACTION
    pick = bet.get("pick") if bet else None
    stake = float(bet.get("stake") or 0.0) if bet else 0.0
    engine_adjustment = bet.get("engine_adjustment") if bet else None

    drivers: list[str] = []
    if eligible:
        if len(eligible) == 1:
            drivers.append(f"Only {eligible[0]} was eligible from the blind forecast.")
        else:
            drivers.append(
                "Eligible from blind forecast: " + ", ".join(eligible) + "."
            )
    if pick and pick in probs:
        implied = (_market_implied(odds) or {}).get(pick)
        if implied is not None:
            if probs[pick] + 1e-12 < implied:
                drivers.append(
                    "The market price was tighter than the agent's own probability."
                )
            elif probs[pick] > implied + 1e-12:
                drivers.append(
                    "The agent's own probability was above the market-implied price."
                )
            else:
                drivers.append("The agent's probability roughly matched the market price.")
    if chosen_pct is not None:
        if chosen_pct == 0:
            drivers.append("The model chose to pass.")
        elif abs((chosen_pct / 100.0) - target) <= 0.001:
            drivers.append("The chosen tier matched the matchday allocation target.")
        elif chosen_pct <= min(stage_stake_tiers(fixture.stage.value)) * 100 + 1e-9:
            drivers.append("The model used the minimum real stake tier.")
    if engine_adjustment:
        drivers.append(f"The engine adjusted the request: {engine_adjustment}.")
    elif bet is not None:
        drivers.append("The engine accepted the request unchanged.")

    return {
        "probabilities": probs,
        "market_implied": _market_implied(odds),
        "eligible": eligible,
        "available_tiers": [tier * 100 for tier in stage_stake_tiers(fixture.stage.value)],
        "chosen_stake_pct": chosen_pct,
        "matchday_target_pct": target * 100,
        "shortfall_penalty_pct": shortfall_penalty * 100,
        "outcome": "pass" if bet and not pick and stake <= 0 else pick,
        "engine_adjustment": engine_adjustment,
        "drivers": drivers,
    }


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
    aggressive = avg_stake_pct > 0.5 * MAX_STAKE_FRACTION  # >10% of bankroll
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


def _style_followthrough(
    constitution: dict | None,
    *,
    bets_placed: int,
    passes: int,
    avg_stake_pct: float,
    roi: float,
) -> dict | None:
    """Coarse public check: does observed betting match the stated constitution profile?"""
    if constitution is None:
        return None
    total = bets_placed + passes
    if total < 3:
        return {
            "score": None,
            "label": "too early",
            "notes": ["Needs at least three locked decisions before style can be judged."],
        }
    pass_rate = passes / total if total else 0.0
    aggression = constitution["aggression"]
    discipline = constitution["bankroll_discipline"]
    notes: list[str] = []
    score = 0

    if aggression == "high":
        ok = avg_stake_pct >= 0.09 or pass_rate <= 0.35
        notes.append("High aggression expects fewer passes or larger average stakes.")
    elif aggression == "low":
        ok = avg_stake_pct <= 0.10 and pass_rate >= 0.25
        notes.append("Low aggression expects selective betting and restrained stake size.")
    else:
        ok = 0.04 <= avg_stake_pct <= 0.16
        notes.append("Medium aggression expects meaningful but not maximal average stakes.")
    score += 1 if ok else 0

    if discipline == "high":
        ok = roi > -0.35 and avg_stake_pct <= 0.18
        notes.append("High discipline expects bankroll damage control and capped average risk.")
    elif discipline == "low":
        ok = avg_stake_pct >= 0.08 or roi > 0
        notes.append("Low discipline tolerates bolder risk if it creates upside.")
    else:
        ok = roi > -0.5
        notes.append("Medium discipline expects losses not to spiral out of control.")
    score += 1 if ok else 0

    label = "following style" if score == 2 else "mixed signals" if score == 1 else "off-style"
    return {"score": score / 2, "label": label, "notes": notes}


def _behavior_profile(
    bets: list,
    ledger: list,
    *,
    bets_placed: int,
    passes: int,
    avg_stake_pct: float,
    roi: float,
    bankroll: float,
) -> list[dict]:
    """Behavior-derived style labels for the public agent page.

    These intentionally replace self-declared low/medium/high labels, which clustered too
    much because every model described itself as disciplined. This uses actual public rows.
    """
    total_decisions = bets_placed + passes
    pass_rate = passes / total_decisions if total_decisions else 0.0
    draw_or_underdog = sum(1 for b in bets if b["pick"] in {"draw", "away"} and (b["stake"] or 0) > 0)
    non_fav_rate = draw_or_underdog / bets_placed if bets_placed else 0.0
    portfolio_hits = sum(1 for e in ledger if e.reason == "portfolio_decay")
    drawdown = max(0.0, (STARTING_BANKROLL - bankroll) / STARTING_BANKROLL)

    if total_decisions < 3:
        risk = "warming up"
    elif pass_rate >= 0.55:
        risk = "selective"
    elif avg_stake_pct >= 0.10:
        risk = "forceful"
    else:
        risk = "balanced"

    if bets_placed < 3:
        price = "unproven"
    elif non_fav_rate >= 0.45:
        price = "value hunter"
    elif non_fav_rate <= 0.15:
        price = "favorite-leaning"
    else:
        price = "selective prices"

    if portfolio_hits >= 2:
        slate = "target misses"
    elif pass_rate <= 0.35 and total_decisions >= 3:
        slate = "active allocator"
    else:
        slate = "patient allocator"

    if drawdown >= 0.20:
        bankroll_state = "under pressure"
    elif roi >= 0.15:
        bankroll_state = "profitable"
    elif avg_stake_pct >= 0.15 and roi < 0:
        bankroll_state = "swingy"
    else:
        bankroll_state = "controlled"

    return [
        {"label": "Risk mode", "value": risk},
        {"label": "Price posture", "value": price},
        {"label": "Slate pressure", "value": slate},
        {"label": "Bankroll state", "value": bankroll_state},
    ]


def _constitution_payload(conn: sqlite3.Connection, model_name: str) -> dict | None:
    """Serialize a public constitution row for the API."""
    c = db.get_agent_constitution(conn, model_name)
    if c is None:
        return None
    return {
        "created_at": c.created_at.isoformat(),
        "principles": c.principles,
        "aggression": c.aggression,
        "favorite_tolerance": c.favorite_tolerance,
        "draw_appetite": c.draw_appetite,
        "contrarian_tendency": c.contrarian_tendency,
        "bankroll_discipline": c.bankroll_discipline,
        "constitution": c.constitution,
    }


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
    ledger = db.list_bankroll_history(conn, c.model_name)
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
    constitution = _constitution_payload(conn, c.model_name)

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
        "constitution": constitution,
        "behavior_profile": _behavior_profile(
            bets,
            ledger,
            bets_placed=len(active_bets),
            passes=passes,
            avg_stake_pct=avg_stake_pct,
            roi=roi,
            bankroll=c.bankroll,
        ),
        "style_followthrough": _style_followthrough(
            constitution,
            bets_placed=len(active_bets),
            passes=passes,
            avg_stake_pct=avg_stake_pct,
            roi=roi,
        ),
    }


def _accuracy_index(
    conn: sqlite3.Connection, *, include_human: bool = False
) -> dict[str, dict]:
    """Index accuracy standings by model name for competitor-card joins."""
    return {
        row["model"]: row
        for row in leaderboard.accuracy_standings(conn, include_human=include_human)
    }


def _usage_index(conn: sqlite3.Connection) -> dict[str, dict]:
    """Index aggregate provider usage by model name."""
    return {row["model_name"]: row for row in db.usage_by_model(conn)}


def list_competitors(conn: sqlite3.Connection) -> list[dict]:
    """Every competitor's character sheet, in bankroll order."""
    acc = _accuracy_index(conn)
    usage = _usage_index(conn)
    return [competitor_card(conn, c, acc, usage) for c in db.list_competitors(conn)]


def competitor_detail(
    conn: sqlite3.Connection, model_name: str, *, include_human: bool = False
) -> dict | None:
    """One character sheet plus bankroll history and a recent bet/prediction log.

    include_human=True is used by the secret challenger's own (authenticated) view so his
    accuracy is graded; public callers leave it False so a hidden human never surfaces.
    """
    c = db.get_competitor(conn, model_name)
    if c is None:
        return None
    # A hidden Human Challenger must never surface on a public (include_human=False) view,
    # even by a direct name lookup, until CHALLENGER_PUBLIC is flipped. His own authenticated
    # /state passes include_human=True, so this only blocks the public competitor route.
    if (
        not include_human
        and not CHALLENGER_PUBLIC
        and model_name in db.human_names(conn)
    ):
        return None
    card = competitor_card(
        conn, c, _accuracy_index(conn, include_human=include_human), _usage_index(conn)
    )

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
            fx_label = {
                "home": h,
                "away": a,
                "stage": fx.stage.value,
                "kickoff": fx.kickoff.isoformat(),
            }
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


def leaderboard_brier(conn: sqlite3.Connection) -> dict:
    """Reasoning board: Brier score on the blind Step-1 forecast (lower = better),
    with agent metadata attached and the uniform-guess baseline for reference."""
    rows = leaderboard.brier_standings(conn)
    for r in rows:
        r["meta"] = agents_meta.meta_for(r["model"])
    return {"standings": rows, "baseline": leaderboard.BRIER_UNIFORM_BASELINE}


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
    upcoming = [
        fx
        for fx in fixtures
        if fx.kickoff >= now and fx.status == MatchStatus.SCHEDULED
    ]
    upcoming.sort(key=lambda fx: fx.kickoff)
    teams = _team_index(conn)
    next_fx = (
        serialize_fixture(
            upcoming[0], teams, _consensus_odds_dict(conn, upcoming[0].id)
        )
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
    # is_human = 0: the secret Human Challenger is excluded from the public headline numbers
    # (competitor count + combined bankroll) just like every other public board.
    n_competitors = conn.execute(
        "SELECT COUNT(*) FROM competitor WHERE active = 1 AND is_human = 0"
    ).fetchone()[0]
    total_bankroll = conn.execute(
        "SELECT COALESCE(SUM(bankroll),0) FROM competitor WHERE is_human = 0"
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
