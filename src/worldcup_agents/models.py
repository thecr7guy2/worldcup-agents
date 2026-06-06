"""Domain models (Pydantic) and enums for the competition.

These are the validated shapes that cross boundaries — data-source adapters,
agents, and persistence all speak in these types. db.py defines the SQLite
schema that mirrors them.

Canonical IDs: team.id is a 1-based index into sources.names.CANONICAL_TEAMS;
fixture.id is openfootball's `num` or a deterministic sort-based surrogate.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class Stage(str, Enum):
    """Tournament stage of a fixture."""

    GROUP = "group"
    R32 = "round_of_32"
    R16 = "round_of_16"
    QF = "quarter_final"
    SF = "semi_final"
    THIRD = "third_place"
    FINAL = "final"


class MatchStatus(str, Enum):
    """Lifecycle of a fixture."""

    SCHEDULED = "scheduled"
    LIVE = "live"
    FINISHED = "finished"
    POSTPONED = "postponed"


class Outcome(str, Enum):
    """A 1X2 match-result outcome — also used as a bet pick."""

    HOME = "home"
    DRAW = "draw"
    AWAY = "away"


class BetResult(str, Enum):
    """How a bet resolved at settlement."""

    WIN = "win"
    LOSS = "loss"
    VOID = "void"  # postponed/abandoned → stake refunded
    PASS = "pass"  # agent chose not to bet


class Team(BaseModel):
    """A national team."""

    id: int  # API-Football team id (canonical)
    name: str
    code: str | None = None  # 3-letter code, e.g. BRA
    group: str | None = None  # A..L; None outside the group stage
    fifa_rank: int | None = None


class Fixture(BaseModel):
    """A single match. The 90-minute result is what settles 1X2 bets.

    Invariant: each side is identified by EITHER *_id (resolved team) OR *_label
    (unresolved bracket slot, e.g. "2A", "W73"), never neither.
    Group fixtures have real ids; knockout fixtures start with labels only and get
    ids filled in by a later bracket-resolution slice.
    """

    id: int  # openfootball num, or deterministic sort-based surrogate
    stage: Stage
    group: str | None = None
    kickoff: datetime  # UTC
    venue: str | None = None
    home_id: int | None = None
    away_id: int | None = None
    home_label: str | None = None  # bracket placeholder, e.g. "2A", "W73"
    away_label: str | None = None
    odds_event_id: str | None = None  # Odds-API event id, cached after first match
    status: MatchStatus = MatchStatus.SCHEDULED
    # Result — filled after the match.
    home_goals_90: int | None = None
    away_goals_90: int | None = None
    went_extra_time: bool = False
    went_penalties: bool = False
    advanced_id: int | None = None  # who progressed (knockouts; penalties count here)

    def result_90(self) -> Outcome | None:
        """1X2 outcome on the 90-minute score, or None if not yet known."""
        if self.home_goals_90 is None or self.away_goals_90 is None:
            return None
        if self.home_goals_90 > self.away_goals_90:
            return Outcome.HOME
        if self.home_goals_90 < self.away_goals_90:
            return Outcome.AWAY
        return Outcome.DRAW


class OddsSnapshot(BaseModel):
    """A frozen pre-match 1X2 odds capture (decimal). Injected only at bet step."""

    fixture_id: int
    captured_at: datetime
    bookmaker: str
    home: float
    draw: float
    away: float


class Prediction(BaseModel):
    """Step 1 — football judgment, made with odds HIDDEN.

    The model commits to a 90-minute scoreline; `winner` is derived from it (one
    source of truth). The score feeds the accuracy leaderboard only — it never
    enters the BET step. Goals are nullable so pre-scoreline rows still load.
    """

    model_name: str
    fixture_id: int
    winner: Outcome
    pred_home_goals: int | None = None
    pred_away_goals: int | None = None
    # Knockouts only: which side the model thinks ultimately PROGRESSES (counting
    # extra time / penalties). HOME or AWAY — never DRAW; None for group fixtures.
    predicted_advance: Outcome | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    created_at: datetime

    @property
    def has_score(self) -> bool:
        return self.pred_home_goals is not None and self.pred_away_goals is not None


class Bet(BaseModel):
    """Step 2 — money judgment, made with odds now visible. pick=None means pass."""

    model_name: str
    fixture_id: int
    pick: Outcome | None = None
    stake: float = 0.0
    odds_at_bet: float | None = None  # decimal odds for the pick at bet time
    reasoning: str = ""
    created_at: datetime

    @property
    def is_pass(self) -> bool:
        return self.pick is None or self.stake <= 0


class Settlement(BaseModel):
    """The result of grading one bet against the actual outcome."""

    model_name: str
    fixture_id: int
    result: BetResult
    payout: float  # returned to the agent (stake*odds on win, stake on void, else 0)
    pnl: float  # net bankroll change (payout - stake); 0 for pass/void
    settled_at: datetime


class Competitor(BaseModel):
    """A competing model's current standing."""

    model_name: str
    bankroll: float
    lives_used: int = 0
    active: bool = True


class BankrollEntry(BaseModel):
    """One line in a competitor's bankroll ledger."""

    model_name: str
    at: datetime
    delta: float
    balance_after: float
    reason: str  # "init" | "bet_settled" | "idle_decay" | "rebuy"
    fixture_id: int | None = None


class TeamDossier(BaseModel):
    """Living per-team state, updated after each match (one row per team).

    Layered so recency stays proportionate: a shock result updates the bounded
    `latest_match` and nudges `rolling_form`, but cannot erase `baseline`.
    """

    team_id: int
    updated_at: datetime
    baseline: str = ""  # slow-moving: quality, ranking, identity
    rolling_form: str = ""  # last 5-6 trend
    latest_match: str = ""  # bounded, length-capped most-recent recap


class PreMatchReport(BaseModel):
    """Frozen per-(team, fixture) report used for prediction. NO odds inside."""

    fixture_id: int
    team_id: int
    cutoff_at: datetime  # temporal-integrity cutoff: nothing after this is included
    content: str


class MatchBriefing(BaseModel):
    """Per-fixture briefing the predictors see: two reports + match context. NO odds."""

    fixture_id: int
    created_at: datetime
    content: str


class PostMatchReport(BaseModel):
    """Per-(team, fixture) recap written after the match; feeds the dossier."""

    fixture_id: int
    team_id: int
    created_at: datetime
    content: str


class ModelCall(BaseModel):
    """Telemetry for one LLM call, captured from the OpenRouter response usage.

    Logged for every call so the technical report can join cost/tokens against
    predictions and settlements (e.g. cost per correct prediction). `cost_usd` is
    OpenRouter's actual billed cost, not an estimate.
    """

    model_name: str
    step: str  # "intelligence" | "briefing" | "predict" | "bet" | "postmatch"
    fixture_id: int | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int | None = None
    generation_id: str | None = None  # OpenRouter generation id, for audit
    created_at: datetime
