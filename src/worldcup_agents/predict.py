"""The five competitors — each a two-step gambler (DESIGN §2, §5).

Every model runs the SAME two steps over the SAME briefing; only the reasoning
engine differs, which is what makes the leaderboard attributable to skill:

    Step 1 PREDICT (odds HIDDEN): briefing -> {winner, confidence, reasoning}
    Step 2 BET     (odds SHOWN) : + bankroll + 25% cap -> {pick, stake} or pass

The system prompt (the gambler mindset induction) is identical for all five —
fairness lives there. Odds are withheld until Step 2 so the football judgment is
uninfluenced by the market. Confidence from Step 1 is the bridge into the stake.
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import db
from .config import MAX_STAKE_FRACTION, PREDICTION_MODELS, ModelSpec
from .llm import LLMError, complete, extract_json
from .models import (
    Bet,
    Fixture,
    MatchBriefing,
    OddsSnapshot,
    Outcome,
    Prediction,
    Stage,
)

# Identical for all five competitors — the only thing held constant is the
# mindset; the variable under test is the model. (DESIGN §5 "mindset induction".)
SYSTEM_GAMBLER = """You are a sharp professional football gambler competing against \
other gamblers at the FIFA World Cup 2026. You started with a $1,000,000 bankroll and \
your sole objective is to grow it as much as possible across the tournament — treat it \
as if your livelihood depends on it.

Principles you live by:
- Bet big ONLY where you see genuine value (your read differs from what the result \
"should" be). Most matches do not offer an edge.
- The World Cup is famous for upsets. Favorites are routinely overrated, and \
underdogs win when specific factors align: an already-qualified side resting \
starters, fatigue or fixture congestion, extreme heat or altitude, a motivation \
mismatch (must-win vs nothing to play for), or a stylistic matchup that neutralises \
the favorite. NEVER pick a side just because it is the favorite — when the facts point \
to a vulnerable favorite or a genuinely live underdog, trust your read and say so. The \
biggest payouts come from correctly-seen upsets.
- Passing is not weakness — disciplined gamblers skip matches with no edge. Betting \
every match bleeds money to the margin.
- Stake size should scale with your conviction, never exceeding the per-match cap.
- You are measured on results, not eloquence. Be decisive."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---- Step 1: PREDICT (odds hidden) ---------------------------------------


def predict(
    conn: sqlite3.Connection,
    model: ModelSpec,
    fixture: Fixture,
    briefing: MatchBriefing,
    home: str,
    away: str,
    *,
    force: bool = False,
) -> Prediction:
    """Step 1: pure football judgment from the briefing, with odds HIDDEN."""
    if not force:
        existing = db.get_prediction(conn, model.name, fixture.id)
        if existing:
            return existing

    is_knockout = fixture.stage != Stage.GROUP
    advance_field = '"advances": "home" | "away", ' if is_knockout else ""
    advance_note = (
        f'\nThis is a KNOCKOUT match: also give "advances" — who you think ultimately '
        f"PROGRESSES counting extra time and penalties ({home}=home, {away}=away). It "
        f"matters most when your 90-minute score is a DRAW; if your score is decisive, "
        f"it is simply the winner."
        if is_knockout
        else ""
    )

    prompt = f"""MATCH: {home} (home) vs {away} (away) — FIFA World Cup 2026.

Predict the EXACT scoreline over 90 minutes (a draw is a real outcome — extra time and \
penalties do NOT count toward this score). Below is the shared, factual briefing. It \
contains NO betting odds by design — judge on football merit alone.

--- BRIEFING ---
{briefing.content}
--- END BRIEFING ---

Respond with ONLY a JSON object, no other text:
{{"home_goals": <int ≥ 0>, "away_goals": <int ≥ 0>, {advance_field}"confidence": \
<0.0-1.0>, "reasoning": "<2-4 sentences on the key factors>"}}
home_goals/away_goals are {home}'s and {away}'s goals after 90 minutes (the 90-minute \
winner follows from them); confidence is how sure you are of the RESULT (win/draw/loss).\
{advance_note}"""

    text, call = complete(
        model.model_id,
        prompt,
        model_name=model.name,
        step="predict",
        fixture_id=fixture.id,
        system=SYSTEM_GAMBLER,
        max_tokens=25000,  # generous — let reasoning models think freely, never capped
        temperature=0.5,
        reasoning_effort="high",  # don't compromise reasoning quality
    )
    db.log_model_call(conn, call)

    data = extract_json(text)
    try:
        home_goals = int(data["home_goals"])
        away_goals = int(data["away_goals"])
    except (KeyError, ValueError, TypeError):
        raise LLMError(f"{model.name}: invalid/missing score in {data!r}")
    if home_goals < 0 or away_goals < 0:
        raise LLMError(f"{model.name}: negative goals in {data!r}")
    # Derive the winner from the scoreline — one source of truth.
    if home_goals > away_goals:
        winner = Outcome.HOME
    elif home_goals < away_goals:
        winner = Outcome.AWAY
    else:
        winner = Outcome.DRAW

    # Knockouts: who advances. A decisive 90' score forces the advancer (the winner);
    # only a predicted 90' DRAW needs the model's explicit call.
    predicted_advance: Outcome | None = None
    if is_knockout:
        if winner is not Outcome.DRAW:
            predicted_advance = winner
        else:
            adv = str(data.get("advances", "")).strip().lower()
            if adv not in {"home", "away"}:
                raise LLMError(
                    f"{model.name}: knockout 90'-draw needs 'advances' home/away in {data!r}"
                )
            predicted_advance = Outcome.HOME if adv == "home" else Outcome.AWAY

    confidence = max(0.0, min(1.0, float(data.get("confidence", 0.0))))
    reasoning = str(data.get("reasoning", "")).strip()

    pred = Prediction(
        model_name=model.name,
        fixture_id=fixture.id,
        winner=winner,
        pred_home_goals=home_goals,
        pred_away_goals=away_goals,
        predicted_advance=predicted_advance,
        confidence=confidence,
        reasoning=reasoning,
        created_at=_now(),
    )
    db.upsert_prediction(conn, pred)
    return pred


# ---- Step 2: BET (odds shown) --------------------------------------------


def _odds_for(odds: OddsSnapshot, pick: Outcome) -> float:
    return {Outcome.HOME: odds.home, Outcome.DRAW: odds.draw, Outcome.AWAY: odds.away}[
        pick
    ]


def bet(
    conn: sqlite3.Connection,
    model: ModelSpec,
    fixture: Fixture,
    prediction: Prediction,
    odds: OddsSnapshot,
    bankroll: float,
    home: str,
    away: str,
    *,
    force: bool = False,
) -> Bet:
    """Step 2: the same model now sees odds + bankroll and sizes a stake (or passes)."""
    if not force:
        existing = db.get_bet(conn, model.name, fixture.id)
        if existing:
            return existing

    cap = bankroll * MAX_STAKE_FRACTION
    prompt = f"""MATCH: {home} (home) vs {away} (away) — 90-minute result.

YOUR earlier prediction (odds were hidden then):
  winner={prediction.winner.value}, confidence={prediction.confidence:.2f}
  reasoning: {prediction.reasoning}

NOW the market 1X2 decimal odds (payout = stake x odds on a win):
  home ({home}): {odds.home}
  draw:          {odds.draw}
  away ({away}): {odds.away}

Your bankroll: ${bankroll:,.0f}. Per-match cap: ${cap:,.0f} (25%).
Bet only where you see value vs these odds; you may PASS (stake 0). Stake must not \
exceed the cap.

Respond with ONLY a JSON object, no other text:
{{"pick": "home" | "draw" | "away" | "pass", "stake": <dollars, 0 to {cap:.0f}>, \
"reasoning": "<1-3 sentences>"}}"""

    text, call = complete(
        model.model_id,
        prompt,
        model_name=model.name,
        step="bet",
        fixture_id=fixture.id,
        system=SYSTEM_GAMBLER,
        max_tokens=25000,  # generous — let reasoning models think freely, never capped
        temperature=0.5,
        reasoning_effort="high",  # don't compromise reasoning quality
    )
    db.log_model_call(conn, call)

    data = extract_json(text)
    raw_pick = str(data.get("pick", "pass")).strip().lower()
    stake = float(data.get("stake", 0) or 0)
    reasoning = str(data.get("reasoning", "")).strip()

    if raw_pick not in {"home", "draw", "away"} or stake <= 0:
        # Pass — record it explicitly (stake 0, no pick).
        result = Bet(
            model_name=model.name,
            fixture_id=fixture.id,
            pick=None,
            stake=0.0,
            odds_at_bet=None,
            reasoning=reasoning,
            created_at=_now(),
        )
    else:
        pick = Outcome(raw_pick)
        stake = min(stake, cap)  # enforce the cap regardless of what the model said
        result = Bet(
            model_name=model.name,
            fixture_id=fixture.id,
            pick=pick,
            stake=round(stake, 2),
            odds_at_bet=_odds_for(odds, pick),
            reasoning=reasoning,
            created_at=_now(),
        )
    db.upsert_bet(conn, result)
    return result


# ---- Orchestration -------------------------------------------------------


def run_fixture(
    conn: sqlite3.Connection, fixture_id: int, *, force: bool = False
) -> list[tuple[Prediction, Bet]]:
    """Run all five competitors through both steps for one fixture (idempotent)."""
    fixture = db.get_fixture(conn, fixture_id)
    if fixture is None:
        raise ValueError(f"no fixture with id {fixture_id}")
    briefing = db.get_match_briefing(conn, fixture_id)
    if briefing is None:
        raise ValueError(
            f"no briefing for fixture {fixture_id} — run "
            f"`python -m worldcup_agents.intelligence brief {fixture_id}` first"
        )
    odds = db.consensus_odds(conn, fixture_id)
    if odds is None:
        raise ValueError(
            f"no consensus odds for fixture {fixture_id} — run "
            "`python -m worldcup_agents.ingest odds` first"
        )

    home = db.get_team(conn, fixture.home_id).name
    away = db.get_team(conn, fixture.away_id).name

    out: list[tuple[Prediction, Bet]] = []
    for model in PREDICTION_MODELS:
        comp = db.get_competitor(conn, model.name)
        bankroll = comp.bankroll if comp else 0.0
        pred = predict(conn, model, fixture, briefing, home, away, force=force)
        b = bet(conn, model, fixture, pred, odds, bankroll, home, away, force=force)
        out.append((pred, b))
    return out


# ---- CLI -----------------------------------------------------------------


def format_reasoning(
    fixture_id: int,
    home: str,
    away: str,
    results: list[tuple[Prediction, Bet]],
) -> str:
    """Markdown of every model's full Step-1 + Step-2 thought process."""
    lines = [f"# Reasoning — fixture {fixture_id}: {home} vs {away}\n"]
    for pred, b in results:
        pick = b.pick.value if b.pick else "pass"
        stake = f"${b.stake:,.0f}" + (
            f" @ {b.odds_at_bet:.2f}" if b.odds_at_bet else ""
        )
        score = (
            f" {pred.pred_home_goals}-{pred.pred_away_goals}" if pred.has_score else ""
        )
        advance = (
            f" · advances: {pred.predicted_advance.value}"
            if pred.predicted_advance
            else ""
        )
        lines.append(f"## {pred.model_name}")
        lines.append(
            f"**Predict:** {pred.winner.value}{score}{advance} "
            f"(confidence {pred.confidence:.2f}) · **Bet:** {pick} {stake}\n"
        )
        lines.append(
            f"**Step 1 — prediction reasoning (odds hidden):**\n\n{pred.reasoning}\n"
        )
        lines.append(f"**Step 2 — bet reasoning (odds shown):**\n\n{b.reasoning}\n")
    return "\n".join(lines)


def _cmd_predict(args: argparse.Namespace) -> None:
    conn = db.connect()
    db.init_db(conn)
    results = run_fixture(conn, args.fixture_id, force=args.force)
    fixture = db.get_fixture(conn, args.fixture_id)
    home = db.get_team(conn, fixture.home_id).name
    away = db.get_team(conn, fixture.away_id).name
    print(f"Fixture {args.fixture_id}: {home} vs {away}\n")
    print(
        f"{'model':<18}{'predict':<8}{'score':>6}{'conf':>7}"
        f"{'bet':>7}{'stake':>12}{'odds':>7}"
    )
    for pred, b in results:
        pick = b.pick.value if b.pick else "pass"
        odds = f"{b.odds_at_bet:.2f}" if b.odds_at_bet else "—"
        score = (
            f"{pred.pred_home_goals}-{pred.pred_away_goals}" if pred.has_score else "—"
        )
        print(
            f"{pred.model_name:<18}{pred.winner.value:<8}{score:>6}{pred.confidence:>7.2f}"
            f"{pick:>7}{b.stake:>12,.0f}{odds:>7}"
        )

    if args.reasons:
        md = format_reasoning(args.fixture_id, home, away, results)
        print("\n" + md)
        out = Path(".cache") / f"reasoning-fixture-{args.fixture_id}.md"
        out.parent.mkdir(exist_ok=True)
        out.write_text(md, encoding="utf-8")
        print(f"\n(saved to {out})")


def main() -> None:
    parser = argparse.ArgumentParser(prog="worldcup_agents.predict")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("predict", help="run all models' predict+bet for a fixture")
    p.add_argument("fixture_id", type=int)
    p.add_argument(
        "--force", action="store_true", help="re-run even if predictions/bets exist"
    )
    p.add_argument(
        "--reasons",
        action="store_true",
        help="print each model's full reasoning and save it to .cache/",
    )
    p.set_defaults(func=_cmd_predict)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
