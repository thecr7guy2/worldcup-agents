"""The secret "Human Challenger" — a write surface letting one human bet alongside the 7
AIs under the SAME rules (DESIGN §5), hidden from the public site until revealed.

This is the ONLY mutating part of the web tier. It is deliberately narrow:

- Every write touches ONLY the challenger's own competitor row (`settings.challenger_name`);
  it can never move an AI's bankroll or write another model's prediction/bet.
- Two steps mirror the AIs exactly: PREDICT with odds hidden, then BET with odds shown. The
  server withholds a fixture's odds until a prediction for it exists, so the odds-hidden
  parity is enforced here, not just in the UI.
- Bets lock at `kickoff - BET_LEAD_HOURS` — the same instant the AIs lock — which also makes
  in-match betting impossible.
- Access is gated by a passphrase (`settings.challenger_key`); an empty key disables the
  whole feature (every route 404s, so its existence stays secret).

The settlement engine, idle decay, bankroll ledger, and accuracy grading need no changes:
they treat the challenger as just another `model_name` (see db.list_competitors /
settlement / leaderboard). Only his *visibility* is suppressed (config.CHALLENGER_PUBLIC).
"""

from __future__ import annotations

import hashlib
import hmac
import math
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .. import db
from ..config import BET_LEAD_HOURS, MAX_STAKE_FRACTION, settings
from ..models import Bet, MatchStatus, Outcome, Prediction
from . import stats

router = APIRouter(prefix="/api/challenger", tags=["challenger"])

_COOKIE = "wc_challenger"
_COOKIE_MAX_AGE = 7 * 24 * 3600  # a week


# ---- auth ----------------------------------------------------------------


def _feature_enabled() -> bool:
    """The feature exists only when a passphrase is configured."""
    return bool(settings.challenger_key)


def _expected_token() -> str:
    """Stateless session token derived from the key (the raw key never enters the cookie)."""
    return hmac.new(
        settings.challenger_key.encode(), b"wc-challenger-v1", hashlib.sha256
    ).hexdigest()


def require_challenger(request: Request) -> str:
    """FastAPI dependency: 404 if the feature is off, 401 unless a valid session cookie is
    present. Returns the challenger's name (its competitor model_name) on success."""
    if not _feature_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    token = request.cookies.get(_COOKIE, "")
    if not token or not hmac.compare_digest(token, _expected_token()):
        raise HTTPException(status_code=401, detail="Locked")
    return settings.challenger_name


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _lock_at(kickoff: datetime) -> datetime:
    """The instant bets close — identical to the AI bet window (config.BET_LEAD_HOURS)."""
    return kickoff - timedelta(hours=BET_LEAD_HOURS)


# ---- request bodies ------------------------------------------------------


class UnlockBody(BaseModel):
    key: str


class PredictBody(BaseModel):
    fixture_id: int
    winner: Outcome  # home | draw | away (your honest 90' call, odds hidden)
    confidence: float = Field(ge=0.0, le=1.0)
    # Optional most-likely 90' scoreline (feeds the exact-score accuracy point, like the AIs).
    home_goals: int | None = Field(default=None, ge=0)
    away_goals: int | None = Field(default=None, ge=0)
    # Knockouts only: who you think ultimately progresses (ET/penalties). home | away.
    advances: Outcome | None = None
    reasoning: str = ""


class BetBody(BaseModel):
    fixture_id: int
    pick: str  # home | draw | away | pass
    stake: float = Field(default=0.0, ge=0.0, allow_inf_nan=False)
    reasoning: str = ""


# ---- shared helpers ------------------------------------------------------


def _require_open_fixture(conn, fixture_id: int):
    """Fetch a fixture that is still open for betting, or raise the right HTTP error."""
    fx = db.get_fixture(conn, fixture_id)
    if fx is None:
        raise HTTPException(status_code=404, detail=f"No fixture {fixture_id}")
    if fx.status != MatchStatus.SCHEDULED:
        raise HTTPException(status_code=409, detail="Fixture is not open for betting")
    if _now() >= _lock_at(fx.kickoff):
        # 423 Locked: past the AI bet window — no late edge, no in-match betting.
        raise HTTPException(
            status_code=423,
            detail="Bets are locked for this match (closes ~50 min before kickoff)",
        )
    return fx


def _odds_dict(conn, fixture_id: int) -> dict | None:
    o = db.consensus_odds(conn, fixture_id)
    if o is None:
        return None
    return {
        "home": o.home,
        "draw": o.draw,
        "away": o.away,
        "bookmaker": o.bookmaker,
        "captured_at": o.captured_at.isoformat(),
    }


# ---- routes --------------------------------------------------------------


@router.post("/unlock")
def unlock(body: UnlockBody, response: Response) -> dict:
    """Validate the passphrase (constant-time) and set the session cookie."""
    if not _feature_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    if not hmac.compare_digest(body.key, settings.challenger_key):
        raise HTTPException(status_code=401, detail="Wrong passphrase")
    response.set_cookie(
        _COOKIE,
        _expected_token(),
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return {"ok": True, "name": settings.challenger_name}


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(_COOKIE, path="/")
    return {"ok": True}


@router.get("/state")
def state(name: str = Depends(require_challenger)) -> dict:
    """The challenger's own standing + the fixtures he can still act on.

    Odds for a fixture are returned ONLY once he has predicted it (odds-hidden parity).
    """
    conn = db.connect()
    try:
        db.ensure_challenger(conn, name)
        standing = stats.competitor_detail(conn, name, include_human=True)

        teams: dict[int, str] = {}

        def team_name(tid: int | None, label: str | None) -> str:
            if tid is None:
                return label or "TBD"
            if tid not in teams:
                t = db.get_team(conn, tid)
                teams[tid] = t.name if t else (label or "TBD")
            return teams[tid]

        now = _now()
        open_fixtures = []
        for fx in db.list_fixtures(conn):
            if fx.status != MatchStatus.SCHEDULED:
                continue
            if now >= _lock_at(fx.kickoff):
                continue  # already locked
            pred = db.get_prediction(conn, name, fx.id)
            bet = db.get_bet(conn, name, fx.id)
            open_fixtures.append(
                {
                    "fixture_id": fx.id,
                    "stage": fx.stage.value,
                    "group": fx.group,
                    "kickoff": fx.kickoff.isoformat(),
                    "lock_at": _lock_at(fx.kickoff).isoformat(),
                    "venue": fx.venue,
                    "home": team_name(fx.home_id, fx.home_label),
                    "away": team_name(fx.away_id, fx.away_label),
                    "is_knockout": fx.stage.value != "group",
                    "has_odds": db.consensus_odds(conn, fx.id) is not None,
                    "prediction": (
                        {
                            "winner": pred.winner.value,
                            "confidence": pred.confidence,
                            "home_goals": pred.pred_home_goals,
                            "away_goals": pred.pred_away_goals,
                            "advances": (
                                pred.predicted_advance.value
                                if pred.predicted_advance
                                else None
                            ),
                        }
                        if pred
                        else None
                    ),
                    # Odds revealed only after a prediction exists (parity with the AIs).
                    "odds": _odds_dict(conn, fx.id) if pred else None,
                    "bet": (
                        {
                            "pick": bet.pick.value if bet.pick else "pass",
                            "stake": bet.stake,
                            "odds_at_bet": bet.odds_at_bet,
                        }
                        if bet
                        else None
                    ),
                }
            )
        return {
            "name": name,
            "max_stake_fraction": MAX_STAKE_FRACTION,
            "standing": standing,
            "open_fixtures": open_fixtures,
        }
    finally:
        conn.close()


@router.post("/predict")
def predict(body: PredictBody, name: str = Depends(require_challenger)) -> dict:
    """Step 1: record your 90' forecast (odds hidden). Returns the odds + your bankroll +
    cap + open exposure so the UI can show the bet step."""
    conn = db.connect()
    try:
        db.ensure_challenger(conn, name)
        fx = _require_open_fixture(conn, body.fixture_id)

        # Odds-hidden parity: the AIs predict a fixture exactly once (predict() returns the
        # existing call). Re-predicting after /predict has already revealed the odds would
        # let a human re-pick with the market in hand, contaminating the PREDICT step that
        # feeds the accuracy board. Lock it to the first prediction, like the AIs.
        if db.get_prediction(conn, name, fx.id) is not None:
            raise HTTPException(
                status_code=409,
                detail="You already predicted this match — the call is locked.",
            )

        is_knockout = fx.stage.value != "group"

        has_score = body.home_goals is not None and body.away_goals is not None
        pred = Prediction(
            model_name=name,
            fixture_id=fx.id,
            winner=body.winner,
            confidence=body.confidence,
            pred_home_goals=body.home_goals if has_score else None,
            pred_away_goals=body.away_goals if has_score else None,
            predicted_advance=body.advances if is_knockout else None,
            reasoning=body.reasoning.strip(),
            created_at=_now(),
        )
        db.upsert_prediction(conn, pred)
        conn.commit()

        comp = db.ensure_challenger(conn, name)
        open_stake, open_count = db.open_exposure(conn, name)
        return {
            "ok": True,
            "bankroll": comp.bankroll,
            "cap": comp.bankroll * MAX_STAKE_FRACTION,
            "open_stake": open_stake,
            "open_count": open_count,
            "odds": _odds_dict(conn, fx.id),
        }
    finally:
        conn.close()


@router.post("/bet")
def place_bet(body: BetBody, name: str = Depends(require_challenger)) -> dict:
    """Step 2: size your stake (odds shown), or pass. Enforces the 25% cap and the lock."""
    conn = db.connect()
    try:
        db.ensure_challenger(conn, name)
        fx = _require_open_fixture(conn, body.fixture_id)

        if db.get_prediction(conn, name, fx.id) is None:
            raise HTTPException(
                status_code=409, detail="Predict this match before betting on it"
            )

        comp = db.ensure_challenger(conn, name)
        cap = comp.bankroll * MAX_STAKE_FRACTION

        raw_pick = body.pick.strip().lower()
        pick = Outcome(raw_pick) if raw_pick in {"home", "draw", "away"} else None
        stake = body.stake if math.isfinite(body.stake) and body.stake > 0 else 0.0

        if pick is None or stake <= 0:
            result = Bet(
                model_name=name,
                fixture_id=fx.id,
                pick=None,
                stake=0.0,
                odds_at_bet=None,
                reasoning=body.reasoning.strip(),
                created_at=_now(),
            )
        else:
            odds = db.consensus_odds(conn, fx.id)
            if odds is None:
                raise HTTPException(
                    status_code=409, detail="No odds available for this match yet"
                )
            odds_for = {
                Outcome.HOME: odds.home,
                Outcome.DRAW: odds.draw,
                Outcome.AWAY: odds.away,
            }[pick]
            stake = min(stake, cap)  # enforce the cap regardless of what was sent
            result = Bet(
                model_name=name,
                fixture_id=fx.id,
                pick=pick,
                stake=round(stake, 2),
                odds_at_bet=odds_for,
                reasoning=body.reasoning.strip(),
                created_at=_now(),
            )
        db.upsert_bet(conn, result)
        conn.commit()
        return {
            "ok": True,
            "pick": result.pick.value if result.pick else "pass",
            "stake": result.stake,
            "odds_at_bet": result.odds_at_bet,
            "cap": cap,
        }
    finally:
        conn.close()
