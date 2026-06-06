# Slice: Data Ingestion (free-tier, openfootball + The Odds API)

**Status:** PLANNED — ready for execution.
**Author of plan:** Opus (researched + live-probed APIs 2026-06-05). **Executor:** Sonnet.
**Read first:** `tasks/DESIGN.md` (source of truth) and this whole file. All API facts below
were verified live today — **do not re-probe** (it burns the 100/day + 500/mo quotas).

---

## 0. Why this slice changed shape (READ — this overrides parts of DESIGN.md §9)

The design assumed **API-Football** as the workhorse and **its integer IDs as canonical**.
Live probing on 2026-06-05 killed that for the live run:

- API-Football **Free plan only serves seasons 2022–2024** (`"Free plans do not have access
  to this season, try from 2022 to 2024."`). It cannot read 2026 fixtures/results/injuries.
  2022–2024 squads are too stale to build 2026 dossiers. **Decision (user): no Pro upgrade.**
  → **API-Football is dropped.** Do not write an API-Football adapter.
- New free data spine:
  - **Schedule skeleton** ← `openfootball/worldcup.json` (`2026/worldcup.json`). Names only.
  - **1X2 odds** ← **The Odds API** (`soccer_fifa_world_cup`, h2h, decimal). Works for 2026.
  - **Results / form / injuries / news** ← the **Intelligence Agent's web search** (later slices).
- Because openfootball has **no integer IDs**, the invariant *"canonical IDs are
  API-Football's integers"* is dead. **New canonical key = the normalized team name; integer
  ids are locally-minted surrogates.** (Both sources use byte-identical names for all 48 teams,
  so exact-match works; we still add a thin normalization layer for robustness.)

### Scope boundary (do NOT scope-creep past this)
- **IN:** seed the 104-match schedule (teams + fixtures incl. knockout bracket placeholders);
  capture consensus 1X2 odds; name normalization; db helpers; verification; doc fixes.
- **OUT (separate later slices):** results ingestion + settlement; dossier/briefing building;
  prediction/bet pipeline. This slice only fills `team`, `fixture`, `odds_snapshot`.

---

## 1. Acceptance criteria (what must be true when done)

1. `uv run python -m worldcup_agents.ingest seed` populates a DB with **exactly 48 teams**
   and **104 fixtures** (72 `group` + 16 R32 + 8 R16 + 4 QF + 2 SF + 1 third + 1 final = 32 KO).
2. Each group has exactly 4 teams; groups are `A`..`L`.
3. Kickoffs are stored in **UTC**. Spot-check: Mexico vs South Africa = `2026-06-11T19:00:00Z`.
4. Knockout fixtures store bracket **labels** (`"2A"`, `"W73"`) and have `NULL` team ids until
   a later bracket-resolution slice fills them; group fixtures have real team ids.
5. `uv run python -m worldcup_agents.ingest odds` writes ≥1 `odds_snapshot` per currently-posted
   event; every snapshot has home/draw/away decimals > 1.0 and `captured_at < kickoff`.
6. **Every** posted Odds-API event maps to a seeded fixture (0 unmatched names). If any name is
   unmatched, the command must **fail loudly** listing the unmatched names — never silently drop.
7. Re-running both commands is **idempotent** (still 48 teams / 104 fixtures / no dup snapshots
   for the same fixture+bookmaker+captured_at).
8. Verification script (below) passes; `ruff`/`black` clean.

---

## 2. Verified API reference (use these — already probed, samples are real)

### 2a. openfootball schedule — `GET https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json`
No key. Top-level: `{"name": "World Cup 2026", "matches": [ ... 104 ... ]}`.
Group match shape:
```json
{ "round": "Matchday 1", "date": "2026-06-11", "time": "13:00 UTC-6",
  "team1": "Mexico", "team2": "South Africa", "group": "Group A", "ground": "Mexico City" }
```
Knockout match shape (team1/team2 are bracket placeholders; `num` present):
```json
{ "round": "Round of 32", "num": 73, "date": "2026-06-28", "time": "12:00 UTC-7",
  "team1": "2A", "team2": "2B", "ground": "Los Angeles (Inglewood)" }
```
- `group` present ⟺ group-stage match. `round` values: `"Matchday 1".."Matchday 17"` (group),
  `"Round of 32"`, `"Round of 16"`, `"Quarter-final"`, `"Semi-final"`, `"Match for third place"`,
  `"Final"`.
- `time` is local with a `UTC±N` suffix (e.g. `"13:00 UTC-6"`, `"12:00 UTC-7"`). Parse the offset
  with regex `r"UTC([+-]\d+)"`, combine with `date`, convert to UTC.
- Group-stage `team1`/`team2` are the 48 real names; knockout ones are labels (`"2A"`, `"1B"`,
  `"W73"` etc.) → store as labels, not teams.

### 2b. The Odds API — base `https://api.the-odds-api.com/v4`, auth `?apiKey=...`
- **Odds:** `GET /sports/soccer_fifa_world_cup/odds?apiKey=…&regions=eu&markets=h2h&oddsFormat=decimal`
  → list of events. 72 posted today; 24 bookmakers each. Sample:
  ```json
  { "id": "80d82d1113934bfbea4ce8daf37a2433", "commence_time": "2026-06-11T19:00:00Z",
    "home_team": "Mexico", "away_team": "South Africa",
    "bookmakers": [ { "key": "marathonbet", "title": "Marathon Bet",
      "last_update": "2026-06-05T17:04:31Z",
      "markets": [ { "key": "h2h", "outcomes": [
        {"name":"Mexico","price":1.44}, {"name":"South Africa","price":8.7},
        {"name":"Draw","price":4.45} ] } ] } ] }
  ```
  Outcome→1X2: `name == home_team` → home, `name == away_team` → away, `name == "Draw"` → draw.
  `commence_time` is authoritative UTC — assert it equals the parsed openfootball kickoff for
  matched events (cross-check in verification).
- **Quota:** response headers `x-requests-remaining` / `x-requests-used`. 1 credit per odds call.
  497 remaining as of this plan. One odds poll = 1 credit, so polling all matchdays fits in 500/mo.
- Knockout events are **not posted yet** (placeholders unresolved) — that's why only 72/104.

### 2c. API-Football — **DO NOT USE.** Documented here only so nobody re-adds it.

---

## 3. Design decisions (pre-made — implement as specified)

### D1. Module layout — new subpackage `src/worldcup_agents/sources/`
- `sources/__init__.py`
- `sources/names.py` — `CANONICAL_TEAMS` (sorted list of 48 names, frozen below), `normalize(name)`
  (strip/casefold/alias map), `team_id_for(name) -> int` (1-based index into `CANONICAL_TEAMS`),
  `is_placeholder(name) -> bool` (True for bracket labels — anything not in the canonical set).
- `sources/openfootball.py` — `fetch_schedule()` (httpx GET + 24h on-disk cache under a
  `.cache/` dir, gitignored), `parse_schedule(raw) -> tuple[list[Team], list[Fixture]]`.
- `sources/oddsapi.py` — `fetch_odds() -> list[dict]` (raw events) and
  `to_snapshots(events, fixtures) -> list[OddsSnapshot]`.
- `ingest.py` (top level) — CLI entry: `python -m worldcup_agents.ingest {seed|odds|verify}`.

Reuse the **httpx + linear-retry pattern from `llm.py`** (same `_RETRY_STATUS`, backoff). Read
`ODDS_API_KEY` from `config.settings` (already present). Add nothing to the LLM path.

### D2. Canonical IDs (replaces the API-Football-id invariant)
- `team_id` = 1-based index of the normalized name in the frozen `CANONICAL_TEAMS` list.
  Deterministic + stable as long as the 48-name set is fixed (it is — qualification complete).
- `fixture_id` = openfootball `num` when present; else **mint deterministically**: sort all 104
  matches by `(date, time, team1, team2)` and assign `1..104` by that order. Store the chosen id;
  re-seed must reproduce identical ids (the sort is total + deterministic).
- Add `odds_event_id TEXT` to the fixture row: once an Odds-API event is matched to a fixture by
  (home/away normalized names + date), cache its event id so later odds polls join by id, not name.

### D3. Model + schema changes (`models.py` + `db.py`) — minimal, additive
`Fixture` knockout sides have no team yet, so:
- Make `home_id: int | None` and `away_id: int | None` (currently required `int`).
- Add `home_label: str | None = None`, `away_label: str | None = None` (bracket placeholders).
- Add `odds_event_id: str | None = None`.
- Invariant to keep in the docstring: *each side is identified by EITHER `*_id` (resolved) OR
  `*_label` (unresolved bracket slot), never neither.*
`db.py`:
- `fixture` table: `home_id`/`away_id` → nullable (drop `NOT NULL`); add `home_label TEXT`,
  `away_label TEXT`, `odds_event_id TEXT`. FK on nullable columns is fine (NULL skips the check).
- `upsert_fixture` / `get_fixture`: round-trip the new fields.
- New helpers: `list_fixtures(conn, *, stage=None) -> list[Fixture]`,
  `team_id_by_name(conn, name) -> int | None`, `upsert_odds_snapshot(conn, snap)`,
  `get_odds_for_fixture(conn, fixture_id) -> list[OddsSnapshot]`.

### D4. Round → Stage mapping
```
group present            -> Stage.GROUP
"Round of 32"            -> Stage.R32
"Round of 16"            -> Stage.R16
"Quarter-final"          -> Stage.QF
"Semi-final"             -> Stage.SF
"Match for third place"  -> Stage.THIRD
"Final"                  -> Stage.FINAL
```
Unknown round name → raise (fail loud; openfootball wording may drift).

### D5. Odds → snapshot policy (v1: consensus, keep it simple)
Per event, across all bookmakers' h2h market, compute the **median** of home/draw/away decimals
→ one `OddsSnapshot` with `bookmaker="consensus"`, `captured_at = now(UTC)`. (The schema PK
`(fixture_id, bookmaker, captured_at)` already lets us re-poll later without clobbering.) Do not
store all 24 books in v1 — median is what the bet step consumes. Skip events whose `bookmakers`
is empty (log a warning, don't fail).

### D6. CANONICAL_TEAMS (frozen — both sources agree byte-for-byte, verified today)
```
Algeria, Argentina, Australia, Austria, Belgium, Bosnia & Herzegovina, Brazil, Canada,
Cape Verde, Colombia, Croatia, Curaçao, Czech Republic, DR Congo, Ecuador, Egypt, England,
France, Germany, Ghana, Haiti, Iran, Iraq, Ivory Coast, Japan, Jordan, Mexico, Morocco,
Netherlands, New Zealand, Norway, Panama, Paraguay, Portugal, Qatar, Saudi Arabia, Scotland,
Senegal, South Africa, South Korea, Spain, Sweden, Switzerland, Tunisia, Turkey, USA, Uruguay,
Uzbekistan
```
`normalize()` alias map (defensive — Odds API may relabel mid-tournament): `{"Türkiye":"Turkey",
"United States":"USA", "Korea Republic":"South Korea", "IR Iran":"Iran",
"Côte d'Ivoire":"Ivory Coast", "Cabo Verde":"Cape Verde", "Bosnia and Herzegovina":"Bosnia &
Herzegovina", "Czechia":"Czech Republic"}`. Anything still unmatched after normalize ⇒ caller fails loud.

---

## 4. Execution checklist (in order; one in-progress at a time)

- [ ] **Docs first (kill the drift):** in `tasks/DESIGN.md §9` and the **`CLAUDE.md`** "Canonical
      IDs" line, replace the API-Football-as-canonical claims with the openfootball + Odds-API
      spine and the new "canonical key = normalized name, ids are minted surrogates" rule. Add a
      one-line pointer to this file.
- [ ] `models.py`: apply D3 `Fixture` changes (+docstring invariant). `uv run python -c` import check.
- [ ] `db.py`: apply D3 schema + helper changes. Bump `SCHEMA_SQL` (it's `CREATE TABLE IF NOT
      EXISTS` — for a throwaway dev DB just delete the file; note that for Sonnet).
- [ ] `sources/names.py`: implement D6 + D2 id minting. Unit-check `team_id_for` is 1..48 unique.
- [ ] `sources/openfootball.py`: `fetch_schedule` (cache) + `parse_schedule` (D1/D2/D4, time→UTC).
- [ ] `sources/oddsapi.py`: `fetch_odds` (D2b) + `to_snapshots` (D5, name-match via `names.normalize`).
- [ ] `ingest.py`: `seed` (schedule → upsert teams+fixtures), `odds` (poll → upsert snapshots,
      cache `odds_event_id`), `verify` (runs the §5 assertions). Argparse subcommands.
- [ ] **Verify** (see §5). Then `ruff check` + `black .`.
- [ ] Update this file's Results section; add any new gotcha to `tasks/lessons.md`.

---

## 5. Verification (project pattern: throwaway DB + inline `uv run python -c`)

```bash
export PATH="$HOME/.local/bin:$PATH"
rm -f /tmp/wc_test.db
WORLDCUP_DB=/tmp/wc_test.db uv run python -m worldcup_agents.ingest seed
WORLDCUP_DB=/tmp/wc_test.db uv run python -m worldcup_agents.ingest odds
WORLDCUP_DB=/tmp/wc_test.db uv run python -m worldcup_agents.ingest verify
```
`verify` (or an inline script) must assert:
- `count(team) == 48`; every group A..L has 4 teams.
- `count(fixture) == 104`; stage counts = {group:72, R32:16, R16:8, QF:4, SF:2, third:1, final:1}.
- Mexico–South Africa fixture `kickoff == 2026-06-11T19:00:00+00:00`.
- Knockout fixtures have `home_id IS NULL AND home_label IS NOT NULL`.
- After `odds`: ≥1 snapshot; all decimals > 1.0; `captured_at < kickoff`; **0 unmatched** event names.
- Run `seed` twice → still 104 fixtures (idempotent).

(Pass DB path via an env var, e.g. extend `DEFAULT_DB_PATH` to read `WORLDCUP_DB` — add that to
`db.py` so tests use a throwaway file. Small, do it.)

---

## 6. Known traps (each one has bitten a similar pipeline)

- **Silent name drop** — if an Odds-API event name doesn't map, never skip it quietly; fail loud
  (AC#6). A dropped event = a match with no odds = an agent that can't bet it.
- **90-min vs final score is NOT this slice.** `/scores` gives only the final aggregate; the
  knockout 90-min/ET/pen split (needed for 1X2 settlement) is deferred to the settlement slice,
  which will lean on the intelligence agent's web search. Don't half-build it here.
- **Timezone offset sign** — `"UTC-6"` means *subtract -6* → add 6h to get UTC (19:00Z for 13:00).
  Verify against the Odds-API `commence_time`, which is ground truth.
- **Idempotency** — `INSERT OR REPLACE` for team/fixture; for snapshots the PK includes
  `captured_at`, so two polls in the same second could collide — use microsecond ISO timestamps.
- **Cache the schedule** — don't hammer GitHub raw on every run; 24h disk cache, gitignore `.cache/`.

---

## 7. Working notes / decisions log
- 2026-06-05: API-Football free season-gate discovery → pivot to openfootball+OddsAPI (this file §0).
- Odds-API consensus = median across books (D5); revisit if books disagree wildly.

## 8. Results (filled 2026-06-05)
- **Files touched:**
  - `CLAUDE.md` — updated Canonical IDs line (openfootball + minted surrogates, API-Football dropped)
  - `tasks/DESIGN.md §9` — replaced API-Football table with openfootball + Odds API spine; updated §10 risks
  - `src/worldcup_agents/models.py` — `Fixture.home_id/away_id` → nullable; added `home_label`, `away_label`, `odds_event_id`; updated docstring
  - `src/worldcup_agents/db.py` — `fixture` schema updated; `DEFAULT_DB_PATH` reads `WORLDCUP_DB` env; added `list_fixtures`, `team_id_by_name`, `upsert_odds_snapshot`, `get_odds_for_fixture`
  - `src/worldcup_agents/sources/__init__.py` — new subpackage
  - `src/worldcup_agents/sources/names.py` — `CANONICAL_TEAMS`, `normalize`, `team_id_for`, `is_placeholder`
  - `src/worldcup_agents/sources/openfootball.py` — `fetch_schedule` (24 h cache) + `parse_schedule` (UTC conversion)
  - `src/worldcup_agents/sources/oddsapi.py` — `fetch_odds` + `to_snapshots` (median consensus)
  - `src/worldcup_agents/ingest.py` — `seed`, `odds`, `verify` subcommands
  - `src/worldcup_agents/llm.py` — fixed pre-existing E402 import ordering
  - `.gitignore` — added `.cache/`
- **How verified:** `uv run python -m worldcup_agents.ingest seed && odds && verify` → PASSED
  (48 teams, 104 fixtures, 72 snapshots, all prices > 1.0, kickoffs correct, idempotent).
  `ruff check` + `black --check` both clean.
- **Follow-ups logged:** none new; R4 (name drift alias map) documented in `DESIGN.md §10`.
