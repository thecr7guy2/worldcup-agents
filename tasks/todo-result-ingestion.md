# Slice: Result ingestion — intelligence agent web-searches concluded results

**Status:** IN PROGRESS. **Executor:** Opus.
**Read first:** DESIGN §3 (data lineage), §4 (temporal integrity), §7 (settlement edge cases);
`tasks/todo.md §6` (results ← intelligence web search, NOT a score API). Settlement consumes the
result this slice produces (`settlement.record_result`).

---

## 0. Why web search, not a score API

API-Football is dropped (free season-gate, L1). openfootball gives the schedule, not a reliable
90'/ET/pens split. The Odds API has no clean 90' split either. Only a **researched source** gives
the **90-minute regulation score + ET/penalties flags + who advanced** — and settlement *must*
have the 90' score (a knockout 1-1 won on pens settles as a DRAW, DESIGN §7). So results come from
the **intelligence agent's web search** — the same funded OpenRouter `web` plugin path that already
powers briefings/post-match (reuse, no new dependency).

## 1. Load-bearing rules

- **Never fabricate.** If the match hasn't kicked off, is in progress, or can't be verified from a
  reliable source → write nothing (status `not_finished`). Fail loud on garbled data.
- **Temporal guard.** Don't even search before kickoff (a result can't exist). Idempotent: skip
  fixtures already FINISHED/POSTPONED (no wasted search).
- **90-minute score is the settlement input.** The prompt demands the regulation score explicitly,
  separate from ET/pens. Integrity check: `went_extra_time`/`went_penalties` ⟹ level at 90'
  (`home_goals_90 == away_goals_90`); a contradiction (e.g. pens with a 2-1 at 90') is rejected.
- **advanced_id** (knockouts only): decisive in 90' → derive the 90' winner; level → the team the
  model reports advanced (penalties count for advancing, never for the 90' score). Group → null.
- The structured result is written through the existing `settlement.record_result` (one writer).

## 2. Design

- **`llm.py`:** promote `extract_json` (was `predict._extract_json`) to a shared public helper next
  to `LLMError` — predict.py and results.py both use it (DRY; llm.py is the LLM-output boundary).
- **`results.py` (NEW):**
  - `SYSTEM_RESULTS` — meticulous-researcher mindset (verified facts only, never guess).
  - `_build_prompt(home, away, fixture)` — asks for strict JSON `{status, home_goals_90,
    away_goals_90, went_extra_time, went_penalties, advanced, source}`.
  - `_parse_result(data, fixture) -> dict` — PURE: validate status/goals, the ET/pens-level
    integrity check, and map `advanced` (home/away/null) → `advanced_id`. Raises `LLMError` on bad
    data.
  - `_apply_parsed(conn, fixture, parsed) -> Fixture | None` — write via `record_result`
    (finished/postponed) or return None (not_finished).
  - `ingest_result(conn, fixture_id, *, model=INTELLIGENCE_MODEL, force=False)` — guards → web
    search (`complete(..., step="result", web_search=True, temperature=0.0)`, logged) → parse →
    apply. Returns the updated `Fixture` if recorded, else None.
  - CLI: `results ingest <fixture_id> [--force]` and `results due` (every kicked-off, unresolved
    fixture — the orchestrator-friendly batch).

## 3. Acceptance criteria

1. Finished group 2-1 → FINISHED, `result_90 == HOME`, `advanced_id` None.
2. Knockout decisive 2-1 → `advanced_id` derived = home; result_90 HOME.
3. Knockout 1-1 (pens, advanced=away) → goals 1/1, `went_penalties` True, `advanced_id`=away,
   `result_90 == DRAW` (settles correctly downstream).
4. ET/pens with a non-level 90' score → `LLMError` (integrity reject).
5. `not_finished` → nothing written, returns None.
6. `postponed` → status POSTPONED (bets will void).
7. Invalid status / missing / negative goals on a finished match → `LLMError`.
8. **Temporal guard:** before kickoff → returns None WITHOUT a web search; already-resolved fixture
   → returns it without searching (idempotent).
9. `extract_json` behaves identically to the old `predict._extract_json`; prediction path intact.
10. `ruff check` + `black --check` clean; settlement/scoring regressions still pass.

## 4. Verification

`scripts/verify_results.py` — synthetic, no network: drives `_parse_result` + `_apply_parsed`
across every case (1-7), and the offline guard paths of `ingest_result` (8, which return before any
LLM call). Plus an `extract_json` equivalence check (9). Live: a CLI smoke `results ingest 103`
proves the pre-kickoff guard end-to-end (the only live path available — opener is 2026-06-11, no
matches concluded yet); and one manual real-search call against a known PAST match confirms the
prompt+JSON round-trips through live web search.

## 5. Working notes / decisions
- Results run AFTER the match (post-match facts) → temporal integrity preserved; this is the input
  to the orchestrator's `ingest → settle → decay → post-match` sequence (next slice).
- Live regression intentionally minimal: 2026 results don't exist yet and web answers aren't
  deterministic; the settlement-critical parse/validate/write logic is fully synthetic-tested.

## 6. Results (2026-06-06 — COMPLETE)
- **Files touched:**
  - `llm.py` — promoted `extract_json` to a shared public helper (was `predict._extract_json`).
  - `predict.py` — now imports `extract_json` from `llm` (dropped its private copy + `json`/`re`).
  - `results.py` (NEW) — `SYSTEM_RESULTS`, `_build_prompt`, `_parse_result` (pure validate/normalize
    + ET/pens-level integrity check), `_resolve_advanced`, `_apply_parsed`, `ingest_result`
    (guards → web search → parse → write via `settlement.record_result`), CLI `ingest` / `due`.
  - `scripts/verify_results.py` (NEW) — synthetic regression for every parse/apply case + the
    offline guards + `extract_json` equivalence.
- **How verified:**
  - `scripts/verify_results.py` PASS (group/knockout/pens-draw/integrity-reject/void/error cases;
    pre-kickoff + idempotent guards return before any LLM call; `extract_json` equivalence).
  - Prior regressions (`verify_settlement.py`, `verify_scoring.py`) still PASS — the `extract_json`
    move didn't disturb the prediction path.
  - **Live CLI guard:** `results ingest 103` on the opener → "no result recorded (not finished /
    not due)" with NO web search (today 2026-06-06 < kickoff 2026-06-11).
  - **Live web search (real data):** ran `ingest_result` on the 2022 WC final. The model returned
    the **90-minute score 2-2** (NOT the 3-3 after extra time), `went_extra_time/penalties=True`,
    `advanced_id=Argentina`, and `result_90()==DRAW` — proving the load-bearing 90'-vs-ET extraction
    against a real match. Telemetry logged (step=result, 3365 tokens, $0.0118).
  - `ruff check` + `black --check` clean (19 files).
- **Decisions:** results via the intelligence model's web search (no new dependency); never
  fabricate (not_finished writes nothing); single result-writer is `settlement.record_result`;
  `extract_json` now shared in `llm.py`.
- **Next:** the orchestrator tick — sequence `ingest (due) → settle → decay → post-match → brief →
  predict/bet` off kickoff times, on a systemd timer.
