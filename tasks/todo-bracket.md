# Slice: Knockout bracket resolution — fill knockout team ids from results

**Status:** PLANNED — ready for execution.
**Read first:** `tasks/DESIGN.md` §3 (data lineage), §4 (temporal integrity), §7 (settlement
edge cases); `tasks/todo-orchestrator.md` (the tick this hooks into). Every stage this depends
on (result ingestion → `advanced_id`, group 90' scores) is already built + verified.

---

## 0. Why this slice exists (the blocker it removes)

The 32 knockout fixtures are seeded with bracket-placeholder **labels** only — `home_id`/
`away_id` are `NULL` (see `ingest`/`tasks/todo.md` AC#4, which explicitly deferred filling
them). Nothing in the codebase ever resolves a label into a team id. Consequence:
`intelligence.brief_fixture` raises when `home_id`/`away_id` is `None`
(`intelligence.py:346`), so `orchestrate.due_for_brief`/`due_for_bet` (gated on
`home_id`) silently skip all 32 knockout fixtures. **Without this slice the competition
quietly runs only the 72 group matches and stops.**

This slice fills those ids from authoritative results, plugged into the orchestrator tick so
it happens automatically — group winners/runners-up the moment the group stage closes, then
each knockout round as the prior round's results land.

Group stage: **Jun 11–27**. R32 starts **Jun 28**. So R32 resolution is the first hard
deadline after kickoff; W/L resolution for R16→Final follows incrementally.

### Scope boundary (do NOT scope-creep)
- **IN:** a resolver that fills knockout `home_id`/`away_id`; pure group-standings logic; a
  single web-fetch of the official R32 bracket used **only** for the third-placed→slot
  assignment (cross-checked); an orchestrator phase; offline verification.
- **OUT:** storing standings tables for the report; a "to-qualify" betting market; fixing
  `predict.run_fixture` to skip eliminated competitors (separate follow-up, `todo-orchestrator.md §6`).

---

## 1. The label grammar (verified against the cached openfootball schedule)

Four label kinds appear in the 32 knockout fixtures (`team1`/`team2`):

| Label | Meaning | Source | Example fixtures |
|---|---|---|---|
| `1{G}` / `2{G}`  (G∈A..L) | group winner / runner-up | **computed** from group standings | 73 `2A` v `2B`, 74 `1E` v … |
| `3{c}/{c}/…`  (5 candidate groups) | a best-third-placed team | **web** (assignment) + computed (set) | 74 `3A/B/C/D/F`, 77 `3C/D/F/G/H` |
| `W{n}` | winner (advancer) of fixture n | **computed** from `fixture[n].advanced_id` | 89 `W74` v `W77` … |
| `L{n}` | loser (non-advancer) of fixture n | **computed** (the side ≠ advancer) | third-place: `L101` v `L102` |

Anchor observation that drives the design: of the 8 R32 fixtures that contain a `3…` slot,
**every one has its other side as a computable `1{G}`/`2{G}` slot** (e.g. 74 = `1E` vs a
third; 77 = `1I` vs a third). The other 8 R32 fixtures are `2x` vs `2y` (both computable).
So the third-placed teams are the ONLY thing we can't derive locally — exactly the one bit
the web fetch resolves.

---

## 2. Resolution tiers (most-authoritative source per label)

### Tier A — `W{n}` / `L{n}` (pure DB, deterministic, no web)
- `W{n}` → `db.get_fixture(n).advanced_id`.
- `L{n}` → the side of fixture n that did **not** advance: `{home_id, away_id} − advanced_id`.
- Resolvable once fixture n is `FINISHED` **and** `advanced_id` is set. (`results._resolve_advanced`
  can leave `advanced_id=None` if a level-at-90' game's advancer was unreported → leave the
  dependent label unresolved and log; a later result re-ingest fixes it.)
- Resolves incrementally each tick as rounds finish; a fixpoint loop (resolve until no change)
  handles the R32→R16→QF→SF→Final/third-place cascade in one pass.

### Tier B — `1{G}` / `2{G}` (pure DB standings, deterministic)
Pure function `group_standings(fixtures) -> dict[group, list[team_id]]` ordered 1st→4th,
over the 6 **FINISHED** group fixtures of each group. FIFA group ranking:
1. points (W=3, D=1, L=0) → 2. goal difference → 3. goals for →
4. **head-to-head** among the still-tied subset (points, then GD, then GF in matches between
   only those teams) → 5. *fair-play (cards) — NOT tracked* → 6. *drawing of lots — random*.

We implement 1–4. If a tie survives H2H (criteria 5–6 need data we don't have), break it
**deterministically by ascending team id** and `log` a loud WARNING naming the group — a real
deep tie is rare and the warning flags it for a manual override. `1{G}` = standings[0],
`2{G}` = standings[1]; standings[2] is the group's third-placed team (feeds Tier C).

### Tier C — `3{candidates}` (computed set, web-fetched assignment, cross-checked)
1. **Rank the 12 thirds** (`rank_thirds`) by points → GD → GF → (same deterministic fallback +
   warning). Top 8 qualify → this is the **set of 8 qualifying groups** (our cross-check key).
2. **Web-fetch the official R32 bracket** once (gated on all 72 group fixtures `FINISHED`):
   16 fixtures as `(home_name, away_name)`, real teams, via `llm.complete(..., web_search=True)`
   + `extract_json` (mirror `results.py`; `INTELLIGENCE_MODEL`, temp 0.0). Name-match with
   `sources.names.normalize` / `db.team_id_by_name`; any unmatched name → **fail loud** (never
   silently drop — same rule as `ingest`).
3. **Anchor + cross-check (web used ONLY for the assignment):** for each R32 fixture that has a
   `3…` slot, compute the anchor (`1{G}`/`2{G}`) team from Tier B; find the web fixture
   containing that anchor; its *other* team is the third for this slot. Assert that third ∈ our
   computed qualifying-thirds set. For the 8 both-`2x` fixtures, fill both sides from Tier B and
   assert the pairing matches the web bracket. **Any mismatch (a computed position team absent
   from the web bracket, or a web third outside our set) → raise, write NOTHING**, surface for
   manual `bracket resolve` after review. This keeps every position slot deterministic and
   verifiable and limits web-trust to *which third pairs with which anchor*.

---

## 3. Design

- **New module `src/worldcup_agents/bracket.py`** (mirrors `results.py`: pure helpers on top,
  impure orchestration + CLI below):
  - Pure: `group_standings(fixtures)`, `rank_thirds(standings)`, label parsers
    (`_parse_pos`, `_parse_third`, `_parse_wl`), `winner_of`/`loser_of`.
  - `resolve_winner_loser(conn) -> int` — fixpoint pass filling `W{n}`/`L{n}`; returns count filled.
  - `fetch_official_r32(model=INTELLIGENCE_MODEL) -> list[tuple[str,str]]` — the one web call.
  - `resolve_r32(conn, *, fetch=fetch_official_r32) -> int` — gated on all-groups-finished AND
    R32 not already filled; computes standings, fetches+cross-checks, fills. `fetch` is injected
    so verification stubs it offline.
  - `resolve_brackets(conn, *, now=None, fetch=fetch_official_r32) -> dict` — entry point: runs
    `resolve_r32` then `resolve_winner_loser`; returns a counts summary.
  - CLI: `bracket status` (read-only: group standings so far + every unresolved knockout label)
    and `bracket resolve` (act).
- **No DB schema change.** Resolution just `db.upsert_fixture` with ids filled; the fixture rows
  are the state. **Idempotency gates are structural:** skip a label already resolved; skip the
  whole R32 web-fetch if every R32 fixture already has both ids (so no wasted quota/LLM call).
  Keep the original `*_label` on the row for audit/provenance (the `id`-resolved invariant holds
  once `*_id` is set).
- **`config.py`:** add `GROUP_LETTERS = "ABCDEFGHIJKL"` (only constant needed).
- **Orchestrator (`orchestrate.py`):** new phase **between post-match (3) and brief (5)** —
  knockout ids must exist before a knockout fixture can be briefed, and resolution consumes the
  freshly-ingested results from phases 1–2 (temporal-integrity order preserved):
  ```
  1 results → 2 settle → 3 post-match → 4 RESOLVE BRACKETS (new) → 5 decay → 6 brief → 7 predict/bet
  ```
  Add `"resolved"` to the summary; wrap in the same per-item try/except so a resolution failure
  never aborts the tick. After resolving, re-`list_fixtures` so newly-filled knockouts are
  visible to brief in the same tick.

---

## 4. Temporal integrity (holds by construction — DESIGN §4)

- R32 resolution is gated on **all 72 group matches FINISHED**, which is strictly before any
  R32 kickoff. The web bracket fetch therefore only ever reads post-group, pre-R32 facts.
- `W{n}`/`L{n}` need fixture n FINISHED — i.e. a prior round — before the dependent fixture.
- No briefing is built until ids exist (existing `brief_fixture` guard), and the resolve phase
  runs before brief in the tick. No future information can leak backward.

---

## 5. Acceptance criteria

1. `group_standings` ranks a constructed group correctly, including a points-tie broken by GD,
   a GD-tie broken by GF, and a three-way tie broken by the **head-to-head** mini-table.
2. `rank_thirds` selects the correct 8 of 12 thirds; an unbreakable tie falls back to ascending
   team id and emits a WARNING.
3. `resolve_winner_loser`: `W{n}` fills with `advanced_id`; `L{n}` fills with the non-advancer;
   a source fixture with `advanced_id=None` leaves its dependents unresolved. Idempotent.
4. `resolve_r32` is a **no-op** (no fetch invoked, no writes) until all 72 group fixtures are
   FINISHED; with all finished + a stubbed `fetch`, position slots fill from standings and
   third-slots from the cross-checked bracket. A stub that places a team outside our computed
   qualifiers, or omits a computed position team, makes `resolve_r32` **raise and write nothing**.
5. Cascade: after R32 ids exist and R32 results carry `advanced_id`, a follow-up resolve fills
   R16 `W{n}`; the chain is reachable through Final + third-place (`L101`/`L102`).
6. Orchestrator: the resolve phase runs after post-match and before brief, appears in the tick
   summary, and the all-future/idle tick remains a **no-op with zero `model_call` rows** (assert
   the bracket fetch is NOT invoked when groups are unfinished).
7. Name-match failure in the fetched bracket fails loud, listing unmatched names.
8. `ruff` + `black` clean; `verify_orchestrate`, `verify_results`, `verify_settlement`,
   `verify_scoring` all still PASS.

---

## 6. Verification — `scripts/verify_bracket.py` (offline, synthetic; project pattern)

Throwaway DB, no network (inject a stub `fetch`):
- Seed 12 groups × 6 fixtures with constructed scores (one group engineered for an H2H tie) →
  assert `group_standings` order and that `1{G}`/`2{G}` resolve to the expected team ids.
- Stub `fetch_official_r32` to return a known-correct bracket → assert all 32 R32 ids fill and
  match expectation; then a deliberately-wrong stub (third from a non-qualifying group) →
  assert `resolve_r32` raises and the DB is untouched.
- Seed R16+ fixtures with `W{n}`/`L{n}` labels; set `advanced_id` on the source fixtures →
  assert W/L resolve and `L` = the non-advancer.
- Groups-incomplete / all-future DB → `resolve_brackets` writes nothing and the stub `fetch` is
  never called (assert via a call counter).

Live smoke: `uv run python -m worldcup_agents.bracket status` on the seeded DB (today, nothing
finished) → standings empty, all 32 knockout labels unresolved, **zero network calls**.

---

## 7. Known traps

- **Silent name drop** — an unmatched team name in the fetched bracket must fail loud (AC#7),
  never be skipped; add aliases to `sources/names.py` (the R4 fix point) if a name drifts.
- **`advanced_id` may be None** on a level-at-90' knockout whose advancer the result step
  couldn't confirm — `W{n}`/`L{n}` then stay unresolved; don't fabricate. A re-ingest of that
  result (now with the advancer) unblocks the next tick.
- **Don't re-fetch the bracket every tick** — gate the web call on "R32 not already fully
  resolved" so it fires at most once (quota + determinism).
- **Postponed group match** ⇒ its group never reaches "all FINISHED" ⇒ R32 stays blocked. Real
  WC matches aren't postponed indefinitely; if it happens, `bracket status` shows the stuck
  group for manual handling. Log, don't paper over it.
- **Fixpoint, not single pass**, for W/L so one tick can cascade several rounds if results
  arrive in a burst; guard with a max-iteration backstop.

---

## 8. Working notes / decisions log

- 2026-06-06: Approach chosen (user) — compute 1st/2nd + thirds *ranking* from DB; web-fetch the
  official R32 bracket used ONLY to resolve the third-placed→slot assignment, cross-checked
  against the computed qualifying set. Rejected: hardcoding FIFA's ~495-row combination table
  (too much error-prone data) and full web-fetch of the bracket (no deterministic backbone).
- Anchor trick: every third-slot R32 fixture has a computable `1{G}`/`2{G}` opponent, so the
  third is identified as "the web opponent of our computed anchor" — web-trust is limited to the
  assignment, and every position slot stays deterministic + verifiable.

## 9. Results (filled 2026-06-06)
- **Files touched:**
  - `src/worldcup_agents/bracket.py` — NEW. Pure helpers (`group_standings`, `rank_thirds`,
    label parsers `_parse_pos`/`_parse_third`/`_parse_wl`, `winner_of`/`loser_of`); Tier-A
    `resolve_winner_loser` (fixpoint), Tier-C `fetch_official_r32` (the one web call) +
    `resolve_r32` (positions + cross-checked thirds, fail-closed), `resolve_brackets` entry
    point; `bracket status` / `bracket resolve` CLI.
  - `src/worldcup_agents/config.py` — added `GROUP_LETTERS`.
  - `src/worldcup_agents/orchestrate.py` — new phase 4 (resolve brackets) between post-match
    and decay/brief; `"resolved"` in the tick summary + CLI line; re-`list_fixtures` after a
    non-empty resolve so newly-filled knockouts are briefable in the same tick.
  - `scripts/verify_bracket.py` — NEW offline regression (synthetic tiebreakers + real
    openfootball schedule, stubbed bracket fetch).
- **Design note (deviation from §2/§3):** `group_standings`/`rank_thirds` gained a
  `warn=True` kwarg. The id-fallback WARNING fires for every group on a result-free DB
  (all teams 0/0/0 → tied), which buried the real signal in `bracket status`. The
  read-only `status` view now passes `warn=False`; resolution keeps it on. `resolve_r32`
  returns *sides* filled (32), matching its docstring.
- **How verified:** `uv run python scripts/verify_bracket.py` → ALL PASS (10 checks incl.
  GD/GF/3-way-H2H tiebreaks, unbreakable-tie warning, W/L cascade with `advanced_id=None`
  left unresolved + idempotent, R32 gating/positions/cross-checked thirds on the REAL
  schedule, fail-closed on bad third + unmatched name with DB untouched, idle no-op).
  Regression: `verify_orchestrate`/`results`/`settlement`/`scoring` all still PASS. Live
  smoke `bracket status` on a seeded throwaway DB → standings render, 32 labels unresolved,
  zero network calls, no warning noise. `ruff` + `black` clean.
- **Follow-ups logged:** `predict.run_fixture` still doesn't skip eliminated competitors
  (pre-existing, `todo-orchestrator.md §6`); deployment/systemd timers still outstanding.
