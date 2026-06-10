# Slice: pre-launch hardening + technical-report data capture (2026-06-10)

Goal: with kickoff <24h away, close the gaps that would either (a) break the live run or
(b) leave the final technical report unable to answer "WHY did this agent behave that way".

## Checklist

- [x] Restate goal + acceptance criteria
- [x] **Raw-output capture** — `model_call` gains `response_text` (verbatim answer) and
      `reasoning_text` (OpenRouter `message.reasoning` trace when the provider exposes it).
      Additive migration via `_add_column_if_missing`; the tick's `init_db` applies it on
      the server automatically. Without this, only the 2-4 sentence parsed `reasoning`
      survives — far too thin for the report's behavioural analysis.
- [x] **LLM timeout 120s → 300s** — predict/bet run at `reasoning_effort=high` with
      25k max_tokens; heavy reasoners routinely think for minutes. 120s timed out exactly
      the calls that matter most and burned retry slots inside the pre-kickoff window.
- [x] **Result double-read confirmation** (`RESULT_CONFIRM_READS = 2`) — a result is
      written only when two independent web-search reads parse to the IDENTICAL result.
      Disagreement raises (visible in tick errors) and retries next tick. Rationale: a
      hallucinated/mis-read 90' score corrupts settlement AND both dossiers irreversibly.
      `not_finished` short-circuits after one read (no wasted search).
- [x] **Nightly DB backups** — `scripts/backup_db.py` (sqlite3 backup API: consistent
      while the tick writes; prunes >21 days) + `deploy/wc-backup.{service,timer}`
      (daily 08:00 UTC, the quiet window) wired into `deploy/install.sh`.
- [x] Doc drift: CLAUDE.md + DESIGN.md said 5 competitors; lineup is 7 (config canonical).
- [x] Verify (see Results).

## Acceptance criteria

- Old DBs migrate in place, old rows untouched; new calls log raw text + trace.
- A disagreeing pair of result reads writes NOTHING and surfaces in `tick` errors.
- An agreeing pair writes exactly the old behaviour's result. Idempotence unchanged.
- All pre-existing verify scripts still pass.

## Results / verification story

- `uv run ruff check src scripts` — clean (one pre-existing format drift in llm.py left alone).
- `.cache/verify_hardening.py` (throwaway DB, mocked httpx/complete, no network):
  15/15 checks — migration + raw round-trip, llm capture (content/reasoning/cost),
  result confirmation (not_finished single-read, disagree→abort, agree→write, idempotent).
- `scripts/verify_{results,orchestrate,settlement,scoring,bracket}.py` — ALL PASS.

## Deliberately NOT done (proposed, needs an owner decision)

- **Failure alerting** (tick errors only reach the journal today): a systemd `OnFailure=`
  unit posting to ntfy/Telegram, plus making `tick` exit non-zero when `s["errors"]` is
  non-empty. Needs a channel choice.
- **report.py analysis module** (Brier/log-loss, calibration bins, CLV, ROI curves): all
  inputs are now captured; build it mid-group-stage when real rows exist to test against.
