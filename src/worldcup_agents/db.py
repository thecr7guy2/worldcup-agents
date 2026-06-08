"""SQLite persistence — schema, connection, init/seed, and typed helpers.

Stdlib sqlite3 only (no ORM). The whole competition state is one portable file
that lives on the server. Datetimes are stored as ISO-8601 text; Pydantic parses
them back on read. Helpers here are the minimal round-trip set; richer repository
functions are added per pipeline as we build them.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import PREDICTION_MODELS, STARTING_BANKROLL
import os

from .models import (
    BankrollEntry,
    Bet,
    BetResult,
    Competitor,
    Fixture,
    LateUpdate,
    MatchBriefing,
    MatchStatus,
    ModelCall,
    OddsSnapshot,
    Outcome,
    PostMatchReport,
    Prediction,
    PreMatchReport,
    Settlement,
    Stage,
    Team,
    TeamDossier,
)

DEFAULT_DB_PATH = Path(os.environ.get("WORLDCUP_DB", "worldcup.db"))

_LEGACY_MODEL_NAMES = {
    "GPT-5.5": "GPT-5.5 Pro",
}

# "group" is a SQL keyword, hence the quoting throughout.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS team (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    code       TEXT,
    "group"    TEXT,
    fifa_rank  INTEGER
);

CREATE TABLE IF NOT EXISTS fixture (
    id              INTEGER PRIMARY KEY,
    stage           TEXT NOT NULL,
    "group"         TEXT,
    kickoff         TEXT NOT NULL,                      -- ISO-8601 UTC
    venue           TEXT,
    home_id         INTEGER REFERENCES team(id),        -- NULL for unresolved knockouts
    away_id         INTEGER REFERENCES team(id),
    home_label      TEXT,                               -- bracket placeholder e.g. "2A"
    away_label      TEXT,
    odds_event_id   TEXT,                               -- Odds-API event id cache
    status          TEXT NOT NULL DEFAULT 'scheduled',
    home_goals_90   INTEGER,
    away_goals_90   INTEGER,
    went_extra_time INTEGER NOT NULL DEFAULT 0,
    went_penalties  INTEGER NOT NULL DEFAULT 0,
    advanced_id     INTEGER REFERENCES team(id)
);

CREATE TABLE IF NOT EXISTS competitor (
    model_name  TEXT PRIMARY KEY,
    bankroll    REAL NOT NULL,
    lives_used  INTEGER NOT NULL DEFAULT 0,
    active      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS odds_snapshot (
    fixture_id   INTEGER NOT NULL REFERENCES fixture(id),
    captured_at  TEXT NOT NULL,
    bookmaker    TEXT NOT NULL,
    home         REAL NOT NULL,
    draw         REAL NOT NULL,
    away         REAL NOT NULL,
    PRIMARY KEY (fixture_id, bookmaker, captured_at)
);

CREATE TABLE IF NOT EXISTS prediction (
    model_name      TEXT NOT NULL,
    fixture_id      INTEGER NOT NULL REFERENCES fixture(id),
    winner          TEXT NOT NULL,                       -- argmax of the 1X2 distribution
    p_home          REAL,                                -- explicit 1X2 distribution (sums to 1)
    p_draw          REAL,
    p_away          REAL,
    pred_home_goals INTEGER,                             -- most-likely 90' scoreline
    pred_away_goals INTEGER,
    exp_home_goals  REAL,                                -- expected goals (Poisson means)
    exp_away_goals  REAL,
    predicted_advance TEXT,                              -- knockout only: home/away who progresses
    confidence      REAL NOT NULL,                       -- = probability of `winner`
    reasoning       TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    PRIMARY KEY (model_name, fixture_id)
);

CREATE TABLE IF NOT EXISTS bet (
    model_name  TEXT NOT NULL,
    fixture_id  INTEGER NOT NULL REFERENCES fixture(id),
    pick        TEXT,                                   -- NULL = pass
    stake       REAL NOT NULL DEFAULT 0,
    odds_at_bet REAL,
    reasoning   TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    PRIMARY KEY (model_name, fixture_id)
);

CREATE TABLE IF NOT EXISTS settlement (
    model_name  TEXT NOT NULL,
    fixture_id  INTEGER NOT NULL REFERENCES fixture(id),
    result      TEXT NOT NULL,
    payout      REAL NOT NULL,
    pnl         REAL NOT NULL,
    settled_at  TEXT NOT NULL,
    PRIMARY KEY (model_name, fixture_id)
);

CREATE TABLE IF NOT EXISTS bankroll_history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name    TEXT NOT NULL,
    at            TEXT NOT NULL,
    delta         REAL NOT NULL,
    balance_after REAL NOT NULL,
    reason        TEXT NOT NULL,
    fixture_id    INTEGER
);

CREATE TABLE IF NOT EXISTS matchday_decay (
    matchday    TEXT PRIMARY KEY,                        -- UTC date, YYYY-MM-DD
    applied_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dossier_update (
    fixture_id  INTEGER NOT NULL REFERENCES fixture(id), -- post-match recap folded into
    team_id     INTEGER NOT NULL REFERENCES team(id),    -- this team's dossier, exactly once
    at          TEXT NOT NULL,
    PRIMARY KEY (fixture_id, team_id)
);

CREATE TABLE IF NOT EXISTS team_dossier (
    team_id      INTEGER PRIMARY KEY REFERENCES team(id),
    updated_at   TEXT NOT NULL,
    baseline     TEXT NOT NULL DEFAULT '',
    rolling_form TEXT NOT NULL DEFAULT '',
    latest_match TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS pre_match_report (
    fixture_id  INTEGER NOT NULL REFERENCES fixture(id),
    team_id     INTEGER NOT NULL REFERENCES team(id),
    cutoff_at   TEXT NOT NULL,
    content     TEXT NOT NULL,
    PRIMARY KEY (fixture_id, team_id)
);

CREATE TABLE IF NOT EXISTS match_briefing (
    fixture_id  INTEGER PRIMARY KEY REFERENCES fixture(id),
    created_at  TEXT NOT NULL,
    content     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS late_update (
    fixture_id  INTEGER PRIMARY KEY REFERENCES fixture(id),
    cutoff_at   TEXT NOT NULL,
    content     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS post_match_report (
    fixture_id  INTEGER NOT NULL REFERENCES fixture(id),
    team_id     INTEGER NOT NULL REFERENCES team(id),
    created_at  TEXT NOT NULL,
    content     TEXT NOT NULL,
    PRIMARY KEY (fixture_id, team_id)
);

CREATE TABLE IF NOT EXISTS model_call (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name        TEXT NOT NULL,
    step              TEXT NOT NULL,
    fixture_id        INTEGER,
    prompt_tokens     INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens      INTEGER NOT NULL DEFAULT 0,
    cost_usd          REAL NOT NULL DEFAULT 0,
    latency_ms        INTEGER,
    generation_id     TEXT,
    created_at        TEXT NOT NULL
);
"""


def connect(path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open a connection with row access by name and foreign keys enforced."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Predict+bet run concurrently (one connection per worker thread); make a writer that
    # finds the DB momentarily locked wait rather than error out with "database is locked".
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create the schema (idempotent), apply column migrations, and seed competitors."""
    conn.executescript(SCHEMA_SQL)
    _migrate_schema(conn)
    seed_competitors(conn)
    conn.commit()


def _add_column_if_missing(
    conn: sqlite3.Connection, table: str, column: str, decl: str
) -> None:
    """Idempotently add a column to an existing table (CREATE IF NOT EXISTS can't).
    table/column/decl are hardcoded literals from _migrate_schema — never user input."""
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Additive migrations for DBs created before a column existed (no data loss)."""
    _add_column_if_missing(conn, "prediction", "pred_home_goals", "INTEGER")
    _add_column_if_missing(conn, "prediction", "pred_away_goals", "INTEGER")
    _add_column_if_missing(conn, "prediction", "predicted_advance", "TEXT")
    _add_column_if_missing(conn, "prediction", "p_home", "REAL")
    _add_column_if_missing(conn, "prediction", "p_draw", "REAL")
    _add_column_if_missing(conn, "prediction", "p_away", "REAL")
    _add_column_if_missing(conn, "prediction", "exp_home_goals", "REAL")
    _add_column_if_missing(conn, "prediction", "exp_away_goals", "REAL")


def seed_competitors(conn: sqlite3.Connection) -> None:
    """Insert each configured model at the starting bankroll, if absent."""
    _migrate_model_names(conn)
    for spec in PREDICTION_MODELS:
        conn.execute(
            "INSERT OR IGNORE INTO competitor (model_name, bankroll) VALUES (?, ?)",
            (spec.name, STARTING_BANKROLL),
        )


def _migrate_model_names(conn: sqlite3.Connection) -> None:
    """Rename configured competitors without losing predictions or bankroll history."""
    model_tables = ("prediction", "bet", "settlement", "bankroll_history", "model_call")
    for old, new in _LEGACY_MODEL_NAMES.items():
        old_exists = conn.execute(
            "SELECT 1 FROM competitor WHERE model_name = ?", (old,)
        ).fetchone()
        new_exists = conn.execute(
            "SELECT 1 FROM competitor WHERE model_name = ?", (new,)
        ).fetchone()
        if not old_exists or new_exists:
            continue
        for table in model_tables:
            conn.execute(
                f"UPDATE {table} SET model_name = ? WHERE model_name = ?",
                (new, old),
            )
        conn.execute(
            "UPDATE competitor SET model_name = ? WHERE model_name = ?",
            (new, old),
        )


# ---- Team ----------------------------------------------------------------


def upsert_team(conn: sqlite3.Connection, team: Team) -> None:
    """Insert or replace a team."""
    conn.execute(
        'INSERT OR REPLACE INTO team (id, name, code, "group", fifa_rank) '
        "VALUES (?, ?, ?, ?, ?)",
        (team.id, team.name, team.code, team.group, team.fifa_rank),
    )
    conn.commit()


def get_team(conn: sqlite3.Connection, team_id: int) -> Team | None:
    """Fetch a team by id, or None."""
    row = conn.execute(
        'SELECT id, name, code, "group", fifa_rank FROM team WHERE id = ?', (team_id,)
    ).fetchone()
    return Team(**dict(row)) if row else None


# ---- Fixture -------------------------------------------------------------


def upsert_fixture(conn: sqlite3.Connection, fx: Fixture) -> None:
    """Insert or replace a fixture."""
    conn.execute(
        "INSERT OR REPLACE INTO fixture "
        '(id, stage, "group", kickoff, venue, home_id, away_id, home_label, away_label, '
        " odds_event_id, status, home_goals_90, away_goals_90, went_extra_time, "
        " went_penalties, advanced_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            fx.id,
            fx.stage.value,
            fx.group,
            fx.kickoff.isoformat(),
            fx.venue,
            fx.home_id,
            fx.away_id,
            fx.home_label,
            fx.away_label,
            fx.odds_event_id,
            fx.status.value,
            fx.home_goals_90,
            fx.away_goals_90,
            int(fx.went_extra_time),
            int(fx.went_penalties),
            fx.advanced_id,
        ),
    )
    conn.commit()


def get_fixture(conn: sqlite3.Connection, fixture_id: int) -> Fixture | None:
    """Fetch a fixture by id, or None."""
    row = conn.execute("SELECT * FROM fixture WHERE id = ?", (fixture_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    return Fixture(
        id=d["id"],
        stage=Stage(d["stage"]),
        group=d["group"],
        kickoff=d["kickoff"],
        venue=d["venue"],
        home_id=d["home_id"],
        away_id=d["away_id"],
        home_label=d["home_label"],
        away_label=d["away_label"],
        odds_event_id=d["odds_event_id"],
        status=MatchStatus(d["status"]),
        home_goals_90=d["home_goals_90"],
        away_goals_90=d["away_goals_90"],
        went_extra_time=bool(d["went_extra_time"]),
        went_penalties=bool(d["went_penalties"]),
        advanced_id=d["advanced_id"],
    )


def list_fixtures(
    conn: sqlite3.Connection, *, stage: Stage | None = None
) -> list[Fixture]:
    """Return all fixtures, optionally filtered by stage."""
    if stage:
        rows = conn.execute(
            "SELECT * FROM fixture WHERE stage = ? ORDER BY kickoff", (stage.value,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM fixture ORDER BY kickoff").fetchall()
    result = []
    for row in rows:
        d = dict(row)
        result.append(
            Fixture(
                id=d["id"],
                stage=Stage(d["stage"]),
                group=d["group"],
                kickoff=d["kickoff"],
                venue=d["venue"],
                home_id=d["home_id"],
                away_id=d["away_id"],
                home_label=d["home_label"],
                away_label=d["away_label"],
                odds_event_id=d["odds_event_id"],
                status=MatchStatus(d["status"]),
                home_goals_90=d["home_goals_90"],
                away_goals_90=d["away_goals_90"],
                went_extra_time=bool(d["went_extra_time"]),
                went_penalties=bool(d["went_penalties"]),
                advanced_id=d["advanced_id"],
            )
        )
    return result


def team_id_by_name(conn: sqlite3.Connection, name: str) -> int | None:
    """Return a team's id given its canonical name, or None if not found."""
    row = conn.execute("SELECT id FROM team WHERE name = ?", (name,)).fetchone()
    return row["id"] if row else None


def upsert_odds_snapshot(conn: sqlite3.Connection, snap: OddsSnapshot) -> None:
    """Insert an odds snapshot; ignores duplicates (same fixture+bookmaker+captured_at)."""
    conn.execute(
        "INSERT OR IGNORE INTO odds_snapshot (fixture_id, captured_at, bookmaker, home, draw, away) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            snap.fixture_id,
            snap.captured_at.isoformat(),
            snap.bookmaker,
            snap.home,
            snap.draw,
            snap.away,
        ),
    )
    conn.commit()


def get_odds_for_fixture(
    conn: sqlite3.Connection, fixture_id: int
) -> list[OddsSnapshot]:
    """Return all odds snapshots for a fixture."""
    rows = conn.execute(
        "SELECT fixture_id, captured_at, bookmaker, home, draw, away "
        "FROM odds_snapshot WHERE fixture_id = ? ORDER BY captured_at",
        (fixture_id,),
    ).fetchall()
    return [OddsSnapshot(**dict(r)) for r in rows]


# ---- Competitor ----------------------------------------------------------


def get_competitor(conn: sqlite3.Connection, model_name: str) -> Competitor | None:
    """Fetch one competitor's standing by model name, or None."""
    row = conn.execute(
        "SELECT model_name, bankroll, lives_used, active FROM competitor "
        "WHERE model_name = ?",
        (model_name,),
    ).fetchone()
    if not row:
        return None
    return Competitor(
        model_name=row["model_name"],
        bankroll=row["bankroll"],
        lives_used=row["lives_used"],
        active=bool(row["active"]),
    )


def list_competitors(conn: sqlite3.Connection) -> list[Competitor]:
    """Return all competitors ordered by bankroll (leaderboard order)."""
    rows = conn.execute(
        "SELECT model_name, bankroll, lives_used, active FROM competitor "
        "ORDER BY bankroll DESC"
    ).fetchall()
    return [
        Competitor(
            model_name=r["model_name"],
            bankroll=r["bankroll"],
            lives_used=r["lives_used"],
            active=bool(r["active"]),
        )
        for r in rows
    ]


# ---- Predictions & bets --------------------------------------------------


def upsert_prediction(conn: sqlite3.Connection, p: Prediction) -> None:
    """Insert or replace one model's Step-1 prediction for a fixture."""
    conn.execute(
        "INSERT OR REPLACE INTO prediction "
        "(model_name, fixture_id, winner, p_home, p_draw, p_away, "
        " pred_home_goals, pred_away_goals, exp_home_goals, exp_away_goals, "
        " predicted_advance, confidence, reasoning, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            p.model_name,
            p.fixture_id,
            p.winner.value,
            p.p_home,
            p.p_draw,
            p.p_away,
            p.pred_home_goals,
            p.pred_away_goals,
            p.exp_home_goals,
            p.exp_away_goals,
            p.predicted_advance.value if p.predicted_advance else None,
            p.confidence,
            p.reasoning,
            p.created_at.isoformat(),
        ),
    )
    conn.commit()


def _row_to_prediction(d: dict) -> Prediction:
    d["winner"] = Outcome(d["winner"])
    if d.get("predicted_advance"):
        d["predicted_advance"] = Outcome(d["predicted_advance"])
    return Prediction(**d)


def get_prediction(
    conn: sqlite3.Connection, model_name: str, fixture_id: int
) -> Prediction | None:
    """Fetch one model's prediction for a fixture, or None."""
    row = conn.execute(
        "SELECT model_name, fixture_id, winner, p_home, p_draw, p_away, "
        "pred_home_goals, pred_away_goals, exp_home_goals, exp_away_goals, "
        "predicted_advance, confidence, reasoning, created_at "
        "FROM prediction WHERE model_name = ? AND fixture_id = ?",
        (model_name, fixture_id),
    ).fetchone()
    if not row:
        return None
    return _row_to_prediction(dict(row))


def upsert_bet(conn: sqlite3.Connection, b: Bet) -> None:
    """Insert or replace one model's Step-2 bet for a fixture (pick=None → pass)."""
    conn.execute(
        "INSERT OR REPLACE INTO bet "
        "(model_name, fixture_id, pick, stake, odds_at_bet, reasoning, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            b.model_name,
            b.fixture_id,
            b.pick.value if b.pick else None,
            b.stake,
            b.odds_at_bet,
            b.reasoning,
            b.created_at.isoformat(),
        ),
    )
    conn.commit()


def get_bet(conn: sqlite3.Connection, model_name: str, fixture_id: int) -> Bet | None:
    """Fetch one model's bet for a fixture, or None."""
    row = conn.execute(
        "SELECT model_name, fixture_id, pick, stake, odds_at_bet, reasoning, created_at "
        "FROM bet WHERE model_name = ? AND fixture_id = ?",
        (model_name, fixture_id),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["pick"] = Outcome(d["pick"]) if d["pick"] else None
    return Bet(**d)


def consensus_odds(conn: sqlite3.Connection, fixture_id: int) -> OddsSnapshot | None:
    """Return the most recent consensus odds snapshot for a fixture, or None."""
    row = conn.execute(
        "SELECT fixture_id, captured_at, bookmaker, home, draw, away "
        "FROM odds_snapshot WHERE fixture_id = ? AND bookmaker = 'consensus' "
        "ORDER BY captured_at DESC LIMIT 1",
        (fixture_id,),
    ).fetchone()
    return OddsSnapshot(**dict(row)) if row else None


def list_bets(conn: sqlite3.Connection, fixture_id: int) -> list[Bet]:
    """Return every persisted bet for a fixture, ordered by model (deterministic)."""
    rows = conn.execute(
        "SELECT model_name, fixture_id, pick, stake, odds_at_bet, reasoning, created_at "
        "FROM bet WHERE fixture_id = ? ORDER BY model_name",
        (fixture_id,),
    ).fetchall()
    out: list[Bet] = []
    for row in rows:
        d = dict(row)
        d["pick"] = Outcome(d["pick"]) if d["pick"] else None
        out.append(Bet(**d))
    return out


# ---- Settlement & bankroll -----------------------------------------------


def get_settlement(
    conn: sqlite3.Connection, model_name: str, fixture_id: int
) -> Settlement | None:
    """Fetch one model's settlement for a fixture, or None. The idempotency guard."""
    row = conn.execute(
        "SELECT model_name, fixture_id, result, payout, pnl, settled_at "
        "FROM settlement WHERE model_name = ? AND fixture_id = ?",
        (model_name, fixture_id),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["result"] = BetResult(d["result"])
    return Settlement(**d)


def record_settlement_batch(
    conn: sqlite3.Connection,
    settlements: list[Settlement],
    competitors: list[Competitor],
    ledger: list[BankrollEntry],
) -> None:
    """Atomically write a batch of settlements: every settlement row, the updated
    competitor standings, and all bankroll-ledger entries — in ONE transaction (single
    commit) so a crash can never leave a payout half-applied or a matchday's bust check
    partly applied. Settling a whole matchday in one call is what lets the bust / re-buy
    rule run once per competitor, independent of the order fixtures settle in (DESIGN §5)."""
    cur = conn.cursor()
    for s in settlements:
        cur.execute(
            "INSERT OR REPLACE INTO settlement "
            "(model_name, fixture_id, result, payout, pnl, settled_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                s.model_name,
                s.fixture_id,
                s.result.value,
                s.payout,
                s.pnl,
                s.settled_at.isoformat(),
            ),
        )
    for c in competitors:
        cur.execute(
            "UPDATE competitor SET bankroll = ?, lives_used = ?, active = ? "
            "WHERE model_name = ?",
            (c.bankroll, c.lives_used, int(c.active), c.model_name),
        )
    for e in ledger:
        cur.execute(
            "INSERT INTO bankroll_history "
            "(model_name, at, delta, balance_after, reason, fixture_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                e.model_name,
                e.at.isoformat(),
                e.delta,
                e.balance_after,
                e.reason,
                e.fixture_id,
            ),
        )
    conn.commit()


def list_bankroll_history(
    conn: sqlite3.Connection, model_name: str
) -> list[BankrollEntry]:
    """Return a competitor's bankroll ledger in chronological order."""
    rows = conn.execute(
        "SELECT model_name, at, delta, balance_after, reason, fixture_id "
        "FROM bankroll_history WHERE model_name = ? ORDER BY id",
        (model_name,),
    ).fetchall()
    return [BankrollEntry(**dict(r)) for r in rows]


def fixtures_on_date(conn: sqlite3.Connection, matchday: str) -> list[Fixture]:
    """Return fixtures whose UTC kickoff date equals `matchday` (YYYY-MM-DD)."""
    rows = conn.execute(
        "SELECT id FROM fixture WHERE date(kickoff) = ? ORDER BY kickoff", (matchday,)
    ).fetchall()
    return [get_fixture(conn, r["id"]) for r in rows]


def staked_by_model_on(conn: sqlite3.Connection, matchday: str) -> dict[str, float]:
    """Total stake each model risked on a matchday's fixtures (UTC date)."""
    rows = conn.execute(
        "SELECT b.model_name AS m, COALESCE(SUM(b.stake), 0) AS staked "
        "FROM bet b JOIN fixture f ON b.fixture_id = f.id "
        "WHERE date(f.kickoff) = ? GROUP BY b.model_name",
        (matchday,),
    ).fetchall()
    return {r["m"]: float(r["staked"]) for r in rows}


def matchday_decayed(conn: sqlite3.Connection, matchday: str) -> bool:
    """True if idle decay has already been applied (and marked) for this matchday."""
    row = conn.execute(
        "SELECT 1 FROM matchday_decay WHERE matchday = ?", (matchday,)
    ).fetchone()
    return row is not None


def record_idle_decay(
    conn: sqlite3.Connection,
    matchday: str,
    applied_at: str,
    competitors: list[Competitor],
    ledger: list[BankrollEntry],
) -> None:
    """Atomically apply one matchday's idle decay: update each competitor's bankroll,
    append `idle_decay` ledger entries, and write the matchday marker — one commit."""
    cur = conn.cursor()
    for c in competitors:
        cur.execute(
            "UPDATE competitor SET bankroll = ? WHERE model_name = ?",
            (c.bankroll, c.model_name),
        )
    for e in ledger:
        cur.execute(
            "INSERT INTO bankroll_history "
            "(model_name, at, delta, balance_after, reason, fixture_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (e.model_name, e.at.isoformat(), e.delta, e.balance_after, e.reason, None),
        )
    cur.execute(
        "INSERT OR IGNORE INTO matchday_decay (matchday, applied_at) VALUES (?, ?)",
        (matchday, applied_at),
    )
    conn.commit()


def list_predictions(conn: sqlite3.Connection) -> list[Prediction]:
    """Return every persisted prediction (for the accuracy leaderboard tally)."""
    rows = conn.execute(
        "SELECT model_name, fixture_id, winner, p_home, p_draw, p_away, "
        "pred_home_goals, pred_away_goals, exp_home_goals, exp_away_goals, "
        "predicted_advance, confidence, reasoning, created_at "
        "FROM prediction"
    ).fetchall()
    return [_row_to_prediction(dict(row)) for row in rows]


def dossier_folded(conn: sqlite3.Connection, fixture_id: int, team_id: int) -> bool:
    """True if this fixture's post-match recap has already been folded into the team's
    dossier — the idempotency guard for the non-idempotent dossier update."""
    row = conn.execute(
        "SELECT 1 FROM dossier_update WHERE fixture_id = ? AND team_id = ?",
        (fixture_id, team_id),
    ).fetchone()
    return row is not None


def mark_dossier_folded(
    conn: sqlite3.Connection, fixture_id: int, team_id: int, at: str
) -> None:
    """Record that this fixture's recap has been folded into the team's dossier."""
    conn.execute(
        "INSERT OR IGNORE INTO dossier_update (fixture_id, team_id, at) VALUES (?, ?, ?)",
        (fixture_id, team_id, at),
    )
    conn.commit()


# ---- Intelligence layer (dossiers / reports / briefings) -----------------


def upsert_dossier(conn: sqlite3.Connection, d: TeamDossier) -> None:
    """Insert or replace a team's living dossier (one row per team)."""
    conn.execute(
        "INSERT OR REPLACE INTO team_dossier "
        "(team_id, updated_at, baseline, rolling_form, latest_match) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            d.team_id,
            d.updated_at.isoformat(),
            d.baseline,
            d.rolling_form,
            d.latest_match,
        ),
    )
    conn.commit()


def get_dossier(conn: sqlite3.Connection, team_id: int) -> TeamDossier | None:
    """Fetch a team's dossier, or None if not yet built."""
    row = conn.execute(
        "SELECT team_id, updated_at, baseline, rolling_form, latest_match "
        "FROM team_dossier WHERE team_id = ?",
        (team_id,),
    ).fetchone()
    return TeamDossier(**dict(row)) if row else None


def upsert_pre_match_report(conn: sqlite3.Connection, r: PreMatchReport) -> None:
    """Insert or replace a frozen per-(fixture, team) pre-match report."""
    conn.execute(
        "INSERT OR REPLACE INTO pre_match_report "
        "(fixture_id, team_id, cutoff_at, content) VALUES (?, ?, ?, ?)",
        (r.fixture_id, r.team_id, r.cutoff_at.isoformat(), r.content),
    )
    conn.commit()


def get_pre_match_report(
    conn: sqlite3.Connection, fixture_id: int, team_id: int
) -> PreMatchReport | None:
    """Fetch a pre-match report for a (fixture, team), or None."""
    row = conn.execute(
        "SELECT fixture_id, team_id, cutoff_at, content FROM pre_match_report "
        "WHERE fixture_id = ? AND team_id = ?",
        (fixture_id, team_id),
    ).fetchone()
    return PreMatchReport(**dict(row)) if row else None


def upsert_match_briefing(conn: sqlite3.Connection, b: MatchBriefing) -> None:
    """Insert or replace the assembled per-fixture briefing (NO odds inside)."""
    conn.execute(
        "INSERT OR REPLACE INTO match_briefing (fixture_id, created_at, content) "
        "VALUES (?, ?, ?)",
        (b.fixture_id, b.created_at.isoformat(), b.content),
    )
    conn.commit()


def get_match_briefing(
    conn: sqlite3.Connection, fixture_id: int
) -> MatchBriefing | None:
    """Fetch the assembled briefing for a fixture, or None."""
    row = conn.execute(
        "SELECT fixture_id, created_at, content FROM match_briefing WHERE fixture_id = ?",
        (fixture_id,),
    ).fetchone()
    return MatchBriefing(**dict(row)) if row else None


def upsert_late_update(conn: sqlite3.Connection, u: LateUpdate) -> None:
    """Insert or replace the per-fixture late delta (confirmed XI/injuries/weather; NO odds)."""
    conn.execute(
        "INSERT OR REPLACE INTO late_update (fixture_id, cutoff_at, content) "
        "VALUES (?, ?, ?)",
        (u.fixture_id, u.cutoff_at.isoformat(), u.content),
    )
    conn.commit()


def get_late_update(conn: sqlite3.Connection, fixture_id: int) -> LateUpdate | None:
    """Fetch the late update for a fixture, or None."""
    row = conn.execute(
        "SELECT fixture_id, cutoff_at, content FROM late_update WHERE fixture_id = ?",
        (fixture_id,),
    ).fetchone()
    return LateUpdate(**dict(row)) if row else None


def upsert_post_match_report(conn: sqlite3.Connection, r: PostMatchReport) -> None:
    """Insert or replace a per-(fixture, team) post-match recap."""
    conn.execute(
        "INSERT OR REPLACE INTO post_match_report "
        "(fixture_id, team_id, created_at, content) VALUES (?, ?, ?, ?)",
        (r.fixture_id, r.team_id, r.created_at.isoformat(), r.content),
    )
    conn.commit()


def get_post_match_report(
    conn: sqlite3.Connection, fixture_id: int, team_id: int
) -> PostMatchReport | None:
    """Fetch a post-match report for a (fixture, team), or None."""
    row = conn.execute(
        "SELECT fixture_id, team_id, created_at, content FROM post_match_report "
        "WHERE fixture_id = ? AND team_id = ?",
        (fixture_id, team_id),
    ).fetchone()
    return PostMatchReport(**dict(row)) if row else None


# ---- Telemetry (for the technical report) --------------------------------


def log_model_call(conn: sqlite3.Connection, call: ModelCall) -> None:
    """Record one LLM call's token/cost usage."""
    conn.execute(
        "INSERT INTO model_call (model_name, step, fixture_id, prompt_tokens, "
        " completion_tokens, total_tokens, cost_usd, latency_ms, generation_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            call.model_name,
            call.step,
            call.fixture_id,
            call.prompt_tokens,
            call.completion_tokens,
            call.total_tokens,
            call.cost_usd,
            call.latency_ms,
            call.generation_id,
            call.created_at.isoformat(),
        ),
    )
    conn.commit()


def usage_by_model(conn: sqlite3.Connection) -> list[dict]:
    """Aggregate calls/tokens/cost per model — the report's headline table."""
    rows = conn.execute(
        "SELECT model_name, COUNT(*) AS calls, "
        " SUM(total_tokens) AS tokens, SUM(cost_usd) AS cost_usd "
        "FROM model_call GROUP BY model_name ORDER BY cost_usd DESC"
    ).fetchall()
    return [dict(r) for r in rows]
