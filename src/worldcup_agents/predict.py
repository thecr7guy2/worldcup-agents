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
import re
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

# Two system prompts, one per step — both identical across all five competitors, so the
# only variable under test stays the model (DESIGN §5 "mindset induction").
#
# Step 1 is a NEUTRAL forecaster: the goal is an accurate, well-calibrated read of the
# match, not a bet. It deliberately carries no money framing and no upset-seeking — that
# bias belongs (in neutral, value-seeking form) only in Step 2, after odds are revealed.
SYSTEM_FORECASTER = """You are a sharp, neutral football analyst forecasting matches at \
the FIFA World Cup 2026. Your sole objective is ACCURACY — the most realistic read of what \
will happen over 90 minutes, not a bold, contrarian, or entertaining take.

Principles you work by:
- Weigh the evidence even-handedly. Do NOT favor a side for being the favorite, and do NOT \
reach for an upset because it would be exciting. Let the specific facts decide.
- Genuine upset factors (an already-qualified side resting starters, fatigue or fixture \
congestion, extreme heat or altitude, a motivation mismatch, a stylistic matchup that \
neutralises the stronger side) matter ONLY when the briefing actually supports them — \
otherwise the stronger, in-form side usually wins.
- Most matches have a clear likeliest outcome; some are genuine coin-flips. Reflect that \
honestly in how confident you are — do not manufacture certainty or drama.
- You are measured on how accurate and well-calibrated your forecasts are. Be decisive \
and concise."""

# Step 2 is the GAMBLER: odds are now visible, so the job is to find mispriced lines and
# size stakes. Value can sit on a favorite or an underdog — chase the edge, never an upset
# for its own sake.
SYSTEM_GAMBLER = """You are a sharp professional football gambler competing against \
other gamblers at the FIFA World Cup 2026. You started with a $1,000,000 bankroll and \
your sole objective is to grow it as much as possible across the tournament — treat it \
as if your livelihood depends on it.

Principles you live by:
- Bet ONLY where you see genuine value — where your own read of the probability differs \
from what the offered odds imply. Value can be on a favorite OR an underdog; chase \
mispriced lines in either direction, never an upset for its own sake. Most matches offer \
no edge.
- Passing is not weakness — disciplined gamblers skip matches with no edge. Betting \
every match bleeds money to the margin.
- Stake size should scale with the size of your edge and your conviction, never exceeding \
the per-match cap.
- You are measured on results, not eloquence. Be decisive."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_score(raw: object) -> tuple[int | None, int | None]:
    """Parse a "home-away" scoreline (tolerates -, en-dash, or :) into a pair of ints.

    Returns (None, None) when absent or unparseable — the most-likely score only feeds the
    optional exact-score accuracy point, so a missing one must not fail the whole forecast.
    """
    if not raw:
        return (None, None)
    parts = re.split(r"[-–:]", str(raw).strip(), maxsplit=1)
    if len(parts) != 2:
        return (None, None)
    try:
        h, a = int(parts[0].strip()), int(parts[1].strip())
    except ValueError:
        return (None, None)
    if h < 0 or a < 0:
        return (None, None)
    return (h, a)


# ---- Step 1: PREDICT (odds hidden) ---------------------------------------


def predict(
    conn: sqlite3.Connection,
    model: ModelSpec,
    fixture: Fixture,
    briefing: MatchBriefing,
    home: str,
    away: str,
    *,
    late_update: str | None = None,
    force: bool = False,
) -> Prediction:
    """Step 1: pure football judgment from the briefing, with odds HIDDEN.

    `late_update`, when present, is the near-kickoff delta (confirmed XI / late injuries /
    weather) appended to the briefing the model reads — still facts only, still no odds.
    """
    if not force:
        existing = db.get_prediction(conn, model.name, fixture.id)
        if existing:
            return existing

    late_block = (
        f"\n\n## Late update (near kickoff)\n{late_update}" if late_update else ""
    )

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

Forecast the 90-MINUTE result (extra time and penalties do NOT count). Below is the \
shared, factual briefing. It contains NO betting odds by design — judge on football \
merit alone.

--- BRIEFING ---
{briefing.content}{late_block}
--- END BRIEFING ---

Give an explicit probability for each 90-minute outcome (they must sum to ~1.0), your \
expected goals for each side, and the single most-likely exact scoreline.

Respond with ONLY a JSON object, no other text:
{{"p_home": <0.0-1.0>, "p_draw": <0.0-1.0>, "p_away": <0.0-1.0>, \
"expected_home_goals": <float ≥ 0>, "expected_away_goals": <float ≥ 0>, \
"most_likely_score": "<home>-<away>", {advance_field}"reasoning": "<2-4 sentences on \
the key factors>"}}
p_home/p_draw/p_away are the probabilities of {home} winning, a draw, and {away} winning \
after 90 minutes; calibrate them honestly. most_likely_score is the single likeliest 90' \
scoreline — it may differ from the most probable outcome, which is fine.{advance_note}"""

    text, call = complete(
        model.model_id,
        prompt,
        model_name=model.name,
        step="predict",
        fixture_id=fixture.id,
        system=SYSTEM_FORECASTER,
        max_tokens=25000,  # generous — let reasoning models think freely, never capped
        temperature=0.5,
        reasoning_effort="high",  # don't compromise reasoning quality
    )
    db.log_model_call(conn, call)

    data = extract_json(text)

    def _prob(key: str) -> float:
        try:
            return max(0.0, float(data[key]))
        except (KeyError, ValueError, TypeError):
            raise LLMError(f"{model.name}: invalid/missing {key} in {data!r}")

    total = _prob("p_home") + _prob("p_draw") + _prob("p_away")
    if total <= 0:
        raise LLMError(f"{model.name}: 1X2 probabilities sum to 0 in {data!r}")
    # Normalise so the distribution sums to exactly 1 regardless of how the model rounded.
    p_home = _prob("p_home") / total
    p_draw = _prob("p_draw") / total
    p_away = _prob("p_away") / total
    probs = {Outcome.HOME: p_home, Outcome.DRAW: p_draw, Outcome.AWAY: p_away}

    # Winner = argmax of the distribution (stable tie-break: home > draw > away). This is
    # now the single source of truth for the outcome — not the most-likely scoreline.
    winner = max(
        (Outcome.HOME, Outcome.DRAW, Outcome.AWAY), key=lambda o: probs[o]
    )
    confidence = probs[winner]

    # Most-likely scoreline + expected goals are context (optional, never block a forecast).
    pred_home_goals, pred_away_goals = _parse_score(data.get("most_likely_score"))

    def _xg(key: str) -> float | None:
        try:
            v = float(data[key])
        except (KeyError, ValueError, TypeError):
            return None
        return v if v >= 0 else None

    exp_home_goals, exp_away_goals = _xg("expected_home_goals"), _xg("expected_away_goals")

    # Knockouts: who advances. A decisive 90' outcome forces the advancer (the winner);
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

    reasoning = str(data.get("reasoning", "")).strip()

    pred = Prediction(
        model_name=model.name,
        fixture_id=fixture.id,
        winner=winner,
        p_home=p_home,
        p_draw=p_draw,
        p_away=p_away,
        pred_home_goals=pred_home_goals,
        pred_away_goals=pred_away_goals,
        exp_home_goals=exp_home_goals,
        exp_away_goals=exp_away_goals,
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

    # Show the model its OWN Step-1 distribution so it can size value against the market,
    # plus the market-implied probabilities (1/odds, margin included) for direct comparison.
    if prediction.has_distribution:
        forecast_line = (
            f"  your 90' probabilities: home {prediction.p_home:.0%} · "
            f"draw {prediction.p_draw:.0%} · away {prediction.p_away:.0%}\n"
            f"  (most likely: {prediction.winner.value}, confidence "
            f"{prediction.confidence:.0%})"
        )
    else:
        forecast_line = (
            f"  winner={prediction.winner.value}, confidence={prediction.confidence:.2f}"
        )

    prompt = f"""MATCH: {home} (home) vs {away} (away) — 90-minute result.

YOUR earlier forecast (odds were hidden then):
{forecast_line}
  reasoning: {prediction.reasoning}

NOW the market 1X2 decimal odds (payout = stake x odds on a win); the percentage is the \
market-implied probability (1/odds, includes the bookmaker margin):
  home ({home}): {odds.home}  (~{1 / odds.home:.0%})
  draw:          {odds.draw}  (~{1 / odds.draw:.0%})
  away ({away}): {odds.away}  (~{1 / odds.away:.0%})

You have an edge when YOUR probability for an outcome is meaningfully higher than the \
market-implied one. Your bankroll: ${bankroll:,.0f}. Per-match cap: ${cap:,.0f} (25%). \
Bet only where you see value; you may PASS (stake 0). Stake must not exceed the cap.

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

    # Near-kickoff delta (built best-effort by the orchestrator just before this); every
    # model reads the SAME late update appended to the SAME briefing — shared facts intact.
    late = db.get_late_update(conn, fixture_id)
    late_content = late.content if late else None

    out: list[tuple[Prediction, Bet]] = []
    for model in PREDICTION_MODELS:
        comp = db.get_competitor(conn, model.name)
        bankroll = comp.bankroll if comp else 0.0
        pred = predict(
            conn, model, fixture, briefing, home, away,
            late_update=late_content, force=force,
        )
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
