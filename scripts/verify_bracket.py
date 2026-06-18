"""Knockout bracket resolution regression test — synthetic + real-schedule, OFFLINE.

    uv run python scripts/verify_bracket.py

Covers tasks/todo-bracket.md §5 acceptance criteria with NO network/LLM:
  - group_standings FIFA tiebreakers (GD, GF, three-way head-to-head)  [AC#1]
  - rank_thirds selects the correct qualifying set                      [AC#2]
  - W{n}/L{n} cascade incl. advanced_id=None left unresolved + idempotent [AC#3, AC#5]
  - resolve_r32 gating (no-op until groups finished), position + cross-checked third
    resolution on the REAL openfootball schedule, and fail-closed on a bad/odd bracket
    (writes nothing)                                                    [AC#4, AC#6, AC#7]
The official R32 bracket fetch is always injected as a stub — zero network calls.
"""

from __future__ import annotations

import logging
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from worldcup_agents import bracket, db
from worldcup_agents.models import Fixture, MatchStatus, Stage, Team
from worldcup_agents.sources.openfootball import fetch_schedule, parse_schedule

NOW = datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc)

# Capture the resolver's tie-break WARNINGs instead of letting them spam stderr (the
# synthetic uniform-thirds construction makes many thirds tie — expected, not a failure).
_WARNINGS: list[str] = []


class _Capture(logging.Handler):
    """Capture bracket warnings for assertions without writing to stderr."""

    def emit(self, record: logging.LogRecord) -> None:
        """Store one warning message."""
        _WARNINGS.append(record.getMessage())


_blog = logging.getLogger("worldcup_agents.bracket")
_blog.handlers = [_Capture()]
_blog.propagate = False
_blog.setLevel(logging.WARNING)


def _g(fid, group, h, a, hg, ag):
    """A FINISHED group fixture with a 90' score."""
    return Fixture(
        id=fid,
        stage=Stage.GROUP,
        group=group,
        kickoff=NOW,
        home_id=h,
        away_id=a,
        status=MatchStatus.FINISHED,
        home_goals_90=hg,
        away_goals_90=ag,
    )


# ---- Part 1: group_standings tiebreakers (pure, no DB) -------------------


def test_standings_tiebreakers() -> None:
    """Verify the implemented FIFA group-ordering criteria."""
    # Group A — ids 1..4. GD breaks 1st/2nd (T1 +5 vs T2 +1); H2H breaks 3rd/4th
    # (T3,T4 both 3pts/-3/1, T4 beat T3 head-to-head).
    a = [
        _g(1, "A", 1, 2, 0, 1),  # T2 beats T1
        _g(2, "A", 1, 3, 3, 0),
        _g(3, "A", 1, 4, 3, 0),
        _g(4, "A", 2, 3, 0, 1),  # T3 beats T2
        _g(5, "A", 2, 4, 1, 0),
        _g(6, "A", 3, 4, 0, 1),  # T4 beats T3
    ]
    # Group B — ids 5..8. GF breaks 1st/2nd: both 7pts/+4, T5 GF6 > T6 GF5.
    b = [
        _g(7, "B", 5, 6, 1, 1),
        _g(8, "B", 5, 7, 3, 1),
        _g(9, "B", 5, 8, 2, 0),
        _g(10, "B", 6, 7, 3, 0),
        _g(11, "B", 6, 8, 1, 0),
        _g(12, "B", 7, 8, 2, 0),
    ]
    # Group C — ids 9..12. Genuine THREE-WAY tie (9,10,11 all 6pts/+3/6) broken by
    # the head-to-head mini-table: 9 (+2) > 10 (GF2) > 11 (GF1); 12 bottom.
    c = [
        _g(13, "C", 9, 10, 3, 0),
        _g(14, "C", 9, 11, 0, 1),  # 11 beats 9
        _g(15, "C", 9, 12, 3, 2),
        _g(16, "C", 10, 11, 2, 0),
        _g(17, "C", 10, 12, 4, 0),
        _g(18, "C", 11, 12, 5, 1),
    ]
    standings = bracket.group_standings(a + b + c)
    assert standings["A"] == [1, 2, 4, 3], standings["A"]  # GD + H2H
    assert standings["B"] == [5, 6, 7, 8], standings["B"]  # GF
    assert standings["C"] == [9, 10, 11, 12], standings["C"]  # 3-way H2H
    print("group_standings tiebreakers (GD / GF / three-way head-to-head): PASS")


def test_rank_thirds() -> None:
    """Verify cross-group ranking of third-placed teams."""
    # Two groups; each third has 3pts. X's third (id 3) beats 4th 4-0 (GD+2);
    # Y's third (id 7) beats 4th 1-0 (GD-1). So id 3 outranks id 7 → top of thirds.
    x = [
        _g(1, "X", 1, 2, 1, 0),
        _g(2, "X", 1, 3, 1, 0),
        _g(3, "X", 1, 4, 1, 0),
        _g(4, "X", 2, 3, 1, 0),
        _g(5, "X", 2, 4, 1, 0),
        _g(6, "X", 3, 4, 4, 0),  # third (3) crushes 4th
    ]
    y = [
        _g(7, "Y", 5, 6, 1, 0),
        _g(8, "Y", 5, 7, 1, 0),
        _g(9, "Y", 5, 8, 1, 0),
        _g(10, "Y", 6, 7, 1, 0),
        _g(11, "Y", 6, 8, 1, 0),
        _g(12, "Y", 7, 8, 1, 0),  # third (7) wins narrowly
    ]
    assert bracket.rank_thirds(x + y) == [3, 7], bracket.rank_thirds(x + y)
    print("rank_thirds orders thirds by GD then GF: PASS")


def test_unbreakable_tie_warns() -> None:
    """Verify untracked fair-play ties emit a review warning."""
    # T1,T2 fully identical and DREW head-to-head -> ranking falls back to ascending id
    # and must emit a loud WARNING (criteria 5-6 untracked). Same for T3,T4.
    g = [
        _g(1, "Z", 1, 2, 1, 1),  # draw
        _g(2, "Z", 1, 3, 2, 0),
        _g(3, "Z", 1, 4, 2, 0),
        _g(4, "Z", 2, 3, 2, 0),
        _g(5, "Z", 2, 4, 2, 0),
        _g(6, "Z", 3, 4, 0, 0),  # draw
    ]
    _WARNINGS.clear()
    standings = bracket.group_standings(g)
    assert standings["Z"] == [1, 2, 3, 4], standings["Z"]  # id fallback after H2H draw
    assert any("head-to-head" in w for w in _WARNINGS), _WARNINGS
    print("unbreakable tie -> ascending-id fallback + WARNING emitted: PASS")


# ---- Part 2: W{n}/L{n} cascade (synthetic) -------------------------------


def test_winner_loser() -> None:
    """Verify winner and loser bracket labels resolve correctly."""
    tmp = Path(tempfile.mkdtemp()) / "wc_wl.db"
    conn = db.connect(tmp)
    db.init_db(conn)
    for i in range(1, 7):
        db.upsert_team(conn, Team(id=i, name=f"T{i}"))

    # Two finished source knockouts (1 advanced from #201; #202 level-at-90', advancer
    # unknown -> advanced_id None) and one finished with a known advancer for L.
    db.upsert_fixture(
        conn,
        Fixture(
            id=201,
            stage=Stage.R32,
            kickoff=NOW,
            home_id=1,
            away_id=2,
            status=MatchStatus.FINISHED,
            home_goals_90=2,
            away_goals_90=0,
            advanced_id=1,
        ),
    )
    db.upsert_fixture(
        conn,
        Fixture(
            id=202,
            stage=Stage.R32,
            kickoff=NOW,
            home_id=3,
            away_id=4,
            status=MatchStatus.FINISHED,
            home_goals_90=1,
            away_goals_90=1,
            went_penalties=True,
            advanced_id=None,  # advancer unconfirmed
        ),
    )
    db.upsert_fixture(
        conn,
        Fixture(
            id=203,
            stage=Stage.R32,
            kickoff=NOW,
            home_id=5,
            away_id=6,
            status=MatchStatus.FINISHED,
            home_goals_90=0,
            away_goals_90=3,
            advanced_id=6,
        ),
    )
    # Dependents: W201 resolvable; W202 NOT (source advanced_id None); L203 -> non-advancer.
    db.upsert_fixture(
        conn,
        Fixture(
            id=301, stage=Stage.R16, kickoff=NOW, home_label="W201", away_label="W202"
        ),
    )
    db.upsert_fixture(
        conn,
        Fixture(
            id=302, stage=Stage.THIRD, kickoff=NOW, home_label="L203", away_label="W201"
        ),
    )

    filled = bracket.resolve_winner_loser(conn)
    f301 = db.get_fixture(conn, 301)
    f302 = db.get_fixture(conn, 302)
    assert f301.home_id == 1, f301  # W201 -> advancer 1
    assert f301.away_id is None, f301  # W202 unresolved (advanced_id None)
    assert f302.home_id == 5, f302  # L203 -> the side that did NOT advance (6 advanced)
    assert f302.away_id == 1, f302  # W201
    assert filled == 3, filled
    # Idempotent: a second pass fills nothing new.
    assert bracket.resolve_winner_loser(conn) == 0
    print(
        "W/L cascade (W resolve, L=non-advancer, advanced_id=None unresolved, idempotent): PASS"
    )


# ---- Part 3: real-schedule R32 resolution (stubbed bracket) --------------

# A valid system of distinct representatives: each third-slot R32 fixture -> the group
# whose third fills it (every pick lies inside that slot's candidate set; 8 groups used).
THIRD_SLOT_GROUP = {
    74: "A",
    77: "C",
    79: "F",
    80: "K",
    81: "B",
    82: "H",
    85: "G",
    87: "D",
}
QUAL_GROUPS = set(THIRD_SLOT_GROUP.values())  # {A,B,C,D,F,G,H,K}


def _seed_real_schedule(conn) -> None:
    """Seed the published tournament schedule into a test database."""
    teams, fixtures = parse_schedule(fetch_schedule())
    for t in teams:
        db.upsert_team(conn, t)
    for f in fixtures:
        db.upsert_fixture(conn, f)


def _synth_group_results(conn) -> None:
    """Transitive results for every group: lower team id finishes higher (strict 9/6/3/0,
    no ties). The 3rd-vs-4th margin encodes thirds ranking — qualifying groups win 4-0 so
    their thirds (GD+2) outrank non-qualifying thirds (GD-1), making QUAL_GROUPS the top 8.
    """
    by_group = defaultdict(list)
    for f in db.list_fixtures(conn):
        if f.stage == Stage.GROUP:
            by_group[f.group].append(f)
    for group, gfx in by_group.items():
        order = sorted(bracket._group_team_ids(gfx))  # r1<r2<r3<r4 by id
        rank = {tid: i for i, tid in enumerate(order)}
        r3, r4 = order[2], order[3]
        for f in gfx:
            hi_home = rank[f.home_id] < rank[f.away_id]
            margin = 1
            if {f.home_id, f.away_id} == {r3, r4}:
                margin = 4 if group in QUAL_GROUPS else 1
            f.home_goals_90, f.away_goals_90 = (margin, 0) if hi_home else (0, margin)
            f.status = MatchStatus.FINISHED
            db.upsert_fixture(conn, f)


def _expected_pair(standings, fx) -> tuple[int, int]:
    """Resolve the expected R32 pairing from standings and slot labels."""

    def side(label, is_home):
        """Resolve one position or qualifying-third slot."""
        pos = bracket._parse_pos(label)
        if pos:
            return standings[pos[1]][pos[0] - 1]
        return standings[THIRD_SLOT_GROUP[fx.id]][2]  # the third

    return side(fx.home_label, True), side(fx.away_label, False)


def test_r32_real_schedule() -> None:
    """Verify R32 resolution against the published fixture structure."""
    tmp = Path(tempfile.mkdtemp()) / "wc_r32.db"
    conn = db.connect(tmp)
    db.init_db(conn)
    _seed_real_schedule(conn)

    r32 = [f for f in db.list_fixtures(conn) if f.stage == Stage.R32]
    assert len(r32) == 16, len(r32)

    # Gate: before any group result, resolve_r32 is a no-op and the stub is NEVER called.
    calls = {"n": 0}

    def counting_stub(c):
        """Count unexpected official-bracket fetch attempts."""
        calls["n"] += 1
        return []

    assert bracket.resolve_r32(conn, fetch=counting_stub) == 0
    assert calls["n"] == 0, "bracket fetch must not fire before groups finish"
    assert all(f.home_id is None for f in r32), "R32 must stay unresolved pre-groups"
    print("resolve_r32 gating (no fetch / no writes until groups FINISHED): PASS")

    _synth_group_results(conn)
    fixtures = db.list_fixtures(conn)
    standings = bracket.group_standings(fixtures)
    # Sanity: every group ranked strictly by id; thirds set = qualifying groups' thirds.
    for g, order in standings.items():
        assert order == sorted(order), (g, order)
    qual_thirds = {standings[g][2] for g in QUAL_GROUPS}
    assert set(bracket.rank_thirds(fixtures)[:8]) == qual_thirds
    print(
        "synthetic group stage -> deterministic standings + correct top-8 thirds: PASS"
    )

    r32 = [f for f in fixtures if f.stage == Stage.R32]
    expected = {f.id: _expected_pair(standings, f) for f in r32}

    def name(tid):
        """Resolve a team id to its seeded display name."""
        return db.get_team(conn, tid).name

    correct_pairs = [(name(h), name(a)) for h, a in (expected[f.id] for f in r32)]

    # (a) A third drawn from a NON-qualifying group -> raise, write nothing.
    bad_idx = next(i for i, f in enumerate(r32) if f.id == 74)
    e_third = standings["E"][2]  # group E is non-qualifying
    anchor_home = name(expected[74][0])  # 1E, the computed anchor
    bad_pairs = list(correct_pairs)
    bad_pairs[bad_idx] = (anchor_home, name(e_third))
    try:
        bracket.resolve_r32(conn, fetch=lambda c: bad_pairs)
        raise AssertionError("expected resolve_r32 to reject a non-qualifying third")
    except ValueError as e:
        assert "not in the computed top-8" in str(e), e
    assert all(
        f.home_id is None for f in db.list_fixtures(conn) if f.stage == Stage.R32
    )

    # (b) An unmatched team name -> fail loud listing it; still nothing written.
    junk_pairs = list(correct_pairs)
    junk_pairs[0] = ("Atlantis", junk_pairs[0][1])
    try:
        bracket.resolve_r32(conn, fetch=lambda c: junk_pairs)
        raise AssertionError("expected resolve_r32 to reject an unmatched name")
    except ValueError as e:
        assert "Atlantis" in str(e), e
    assert all(
        f.home_id is None for f in db.list_fixtures(conn) if f.stage == Stage.R32
    )
    print(
        "resolve_r32 fail-closed (bad third / unmatched name -> raise, DB untouched): PASS"
    )

    # (c) Correct bracket -> all 32 sides fill, matching the deterministic expectation.
    filled = bracket.resolve_r32(conn, fetch=lambda c: correct_pairs)
    assert filled == 32, filled
    for f in db.list_fixtures(conn):
        if f.stage == Stage.R32:
            assert (f.home_id, f.away_id) == expected[f.id], (
                f.id,
                f.home_id,
                f.away_id,
            )
    # Idempotent + no re-fetch once resolved.
    calls["n"] = 0
    assert bracket.resolve_r32(conn, fetch=counting_stub) == 0
    assert calls["n"] == 0
    print("resolve_r32 fills all 32 sides from positions + cross-checked thirds: PASS")

    # (d) Cascade onto the REAL R16: mark every R32 home side as the advancer, then the
    # W{n} slots of R16 must fill from advanced_id.
    for f in db.list_fixtures(conn):
        if f.stage == Stage.R32:
            f.status = MatchStatus.FINISHED
            f.home_goals_90, f.away_goals_90 = 1, 0
            f.advanced_id = f.home_id
            db.upsert_fixture(conn, f)
    bracket.resolve_winner_loser(conn)
    f89 = db.get_fixture(conn, 89)  # W74 vs W77
    assert f89.home_id == db.get_fixture(conn, 74).advanced_id, f89
    assert f89.away_id == db.get_fixture(conn, 77).advanced_id, f89
    print("cascade onto real R16 (W{n} <- advanced_id): PASS")


def test_resolve_brackets_idle() -> None:
    """A freshly-seeded, result-free schedule: resolve_brackets writes nothing and never
    fetches (matches the orchestrator idle-tick no-op contract)."""
    tmp = Path(tempfile.mkdtemp()) / "wc_idle.db"
    conn = db.connect(tmp)
    db.init_db(conn)
    _seed_real_schedule(conn)
    calls = {"n": 0}

    def counting_stub(c):
        """Count official-bracket fetch attempts during an idle tick."""
        calls["n"] += 1
        return []

    counts = bracket.resolve_brackets(conn, fetch=counting_stub)
    assert counts == {"r32": 0, "winner_loser": 0}, counts
    assert calls["n"] == 0
    assert all(
        f.home_id is None for f in db.list_fixtures(conn) if f.stage != Stage.GROUP
    )
    print("resolve_brackets idle no-op (no fetch, no writes): PASS")


def main() -> None:
    """Run all bracket acceptance checks."""
    test_standings_tiebreakers()
    test_rank_thirds()
    test_unbreakable_tie_warns()
    test_winner_loser()
    test_r32_real_schedule()
    test_resolve_brackets_idle()
    print("\nALL ACCEPTANCE CRITERIA PASS")


if __name__ == "__main__":
    main()
