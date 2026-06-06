# Slice: Settlement engine — grade bets → apply PnL → bust/re-buy

**Status:** IN PROGRESS. **Executor:** Opus.
**Read first:** DESIGN §5 (gambler model / bust rule), §6 (leaderboards), §7 (settlement edge
cases). Prediction loop is done — see `tasks/todo-prediction.md`. This is its named "next slice".

---

## 0. Scope

- **IN:** for one finished fixture, grade every persisted bet against the **90-minute** 1X2
  result, apply the net PnL to each competitor's bankroll, write an auditable ledger entry, and
  handle the **bust → re-buy / elimination** rule. Plus a `result` command to record a 90-min
  score (synthetic for now; a real result-ingestion slice replaces it later) and a `settle`
  command. Print resulting bankroll standings.
- **OUT (next slice):** idle-cash decay (matchday-level, anti-cowardice), the two formal
  leaderboards (bankroll + accuracy points), real result ingestion (web/API).

## 1. Load-bearing rules (breaking any silently corrupts the competition)

- **Settle on the 90-minute score only** (DESIGN §7). A knockout 1–1 won on penalties settles as
  a **DRAW** — a bet on either team LOSES. `Fixture.result_90()` is the single source; it already
  ignores ET/pens. Do not look at `advanced_id` for settlement.
- **Net-PnL model (no escrow).** `bet()` never deducted the stake; bankroll moves ONLY at
  settlement by `pnl`. So: WIN → `pnl = stake*(odds-1)`; LOSS → `pnl = -stake`; VOID/PASS → `0`.
  `payout` is informational (`stake*odds` win / `stake` void / else 0).
- **Stake can't bust you in one bet** — cap is 25% of bankroll, so a loss is ≥ -25%; bankroll
  never goes negative. Bust is attrition across many losses crossing `BANKRUPT_FLOOR` ($10k).
- **Bust → ONE re-buy** (`MAX_LIVES=1`): reset bankroll to `REBUY_AMOUNT` ($100k), `lives_used+=1`,
  stay active. Out of lives → `active=False` (eliminated), bankroll frozen.
- **Idempotent + atomic.** Settlement applies exactly once per (model, fixture). The
  `settlement` PK guards re-application; settlement-row + competitor-update + ledger write happen
  in ONE transaction (one commit) so a crash can't half-apply a payout.
- **VOID = postponed/abandoned** (DESIGN §7): stake refunded, `pnl=0`.

## 2. Design

### `grade_bet(fixture, bet) -> (BetResult, payout, pnl)` — pure, no DB
- `fixture.status == POSTPONED` → `(VOID, stake, 0)`.
- `bet.is_pass` → `(PASS, 0, 0)`.
- else require `result_90()` (raise if None): `pick == result_90` → `(WIN, stake*odds, stake*(odds-1))`;
  else `(LOSS, 0, -stake)`.

### `_resolve_standing(comp, pnl, fixture_id, at) -> (Competitor, list[BankrollEntry])` — pure
- `balance = comp.bankroll + pnl`; if `pnl != 0` push a `bet_settled` ledger entry.
- if `balance <= BANKRUPT_FLOOR`: lives left → push `rebuy` entry (delta `REBUY_AMOUNT-balance`),
  `balance=REBUY_AMOUNT`, `lives_used+=1`; else `active=False`.

### `settle_fixture(conn, fixture_id) -> list[Settlement]` — orchestration, idempotent
- Load fixture; require `status==POSTPONED` OR a recorded 90-min result, else raise (tell the
  user to run `result` first). Iterate `list_bets` (ordered, deterministic). Skip bets that
  already have a settlement row (return existing). For the rest: grade → resolve standing →
  `db.record_settlement` (atomic) → collect.

### `record_result(conn, fixture_id, home, away, *, et, pens, advanced_id, postponed)` 
- Load fixture, set score + flags + `status` (FINISHED / POSTPONED), `upsert_fixture`.

### CLI (`python -m worldcup_agents.settlement ...`)
- `result <fid> <home_goals> <away_goals> [--et] [--pens] [--advanced TEAM_ID]` / `result <fid> --postpone`
- `settle <fid>` — grade + apply, then print a settlement table and current bankroll standings.

### New `db.py` helpers
- `list_bets(conn, fixture_id) -> list[Bet]` (ORDER BY model_name).
- `get_settlement(conn, model_name, fixture_id) -> Settlement | None` (idempotency guard).
- `record_settlement(conn, settlement, competitor, ledger)` — atomic writer (settlement row +
  competitor standing + bankroll_history entries), single commit.

## 3. Acceptance criteria

1. WIN: `pnl == stake*(odds-1)`, bankroll rises by exactly that; settlement `result=win`.
2. LOSS: `pnl == -stake`, bankroll falls by stake; `result=loss`.
3. PASS bet → `result=pass`, pnl 0, bankroll unchanged, no ledger row.
4. POSTPONED fixture → all bets `result=void`, pnl 0, bankroll unchanged.
5. **§7 edge:** 1–1 with `went_penalties` + `advanced_id` set, a `home` bet → `result=loss`
   (settles as draw on 90'). The decisive regression test.
6. **Bust→re-buy:** a loss dropping bankroll ≤ $10k with a life left → bankroll reset to $100k,
   `lives_used=1`, `active=1`, a `rebuy` ledger entry written. Second bust with no life →
   `active=0`, bankroll frozen.
7. Atomic + idempotent: re-running `settle` makes **no** further bankroll change and adds no
   ledger rows; settlement rows unchanged.
8. `ruff check` + `black --check` clean.

## 4. Verification

Self-contained synthetic unit (no LLM/network) on a throwaway DB — isolates settlement math from
the prediction stage and is a permanent regression test:
- seed teams + one fixture; hand-write bets via `db.upsert_bet` (a winner, a loser, a pass, a
  bust-then-rebuy case, and the 1–1-pens `home` loss); record a synthetic result; `settle_fixture`;
  assert every AC above incl. the idempotent re-run.

```bash
export PATH="$HOME/.local/bin:$PATH"
rm -f /tmp/wc_settle.db
WORLDCUP_DB=/tmp/wc_settle.db uv run python - <<'PY'  # (script in §5 commit)
...assertions...
PY
ruff check src/ && black --check src/
```

## 5. Working notes / decisions
- Re-buy SETS bankroll to $100k (a fresh "second life"), not add — per DESIGN §5 "$100k = 10% of
  start". Ledger delta records the top-up so the trail still sums.
- `force` re-settle intentionally NOT supported: re-applying PnL would need to reverse the prior
  delta first (out of scope). Idempotency = skip-if-settled. Re-runs on a fresh DB only.
- Settlement iterates the bets that EXIST for the fixture (not `PREDICTION_MODELS`), so it's robust
  to lineup changes.

## 6. Results (2026-06-06 — COMPLETE)
- **Files touched:**
  - `src/worldcup_agents/settlement.py` (NEW) — `grade_bet` (pure 90' grading),
    `_resolve_standing` (pure PnL + bust→re-buy/elimination), `settle_fixture` (idempotent
    orchestration), `record_result` (manual score/postpone input), and a `result` / `settle`
    argparse CLI that prints a settlement table + bankroll standings.
  - `src/worldcup_agents/db.py` — imports `BankrollEntry`/`BetResult`/`Settlement`; added
    `list_bets`, `get_settlement`, `record_settlement` (atomic settlement-row + competitor +
    ledger in one commit), `list_bankroll_history`.
  - `scripts/verify_settlement.py` (NEW) — self-contained synthetic regression (temp DB, no
    LLM/network) asserting every AC, kept as a permanent guard for the DESIGN §7 edge case.
- **How verified:** `uv run python scripts/verify_settlement.py` → all ACs PASS (WIN pnl
  `stake*(odds-1)`, LOSS `-stake`, PASS/VOID unchanged + no ledger row, bust→re-buy resets to
  $100k/1 life, second bust→eliminated & frozen, idempotent re-settle, and the knockout 1-1-on-pens
  → DRAW → home bet LOSES). CLI smoke-tested on a seeded opener (GPT-5.5 $150k @1.44 → +$66k,
  pass recorded, idempotent re-run stable). `uv run ruff check src/` + `black --check` clean (13
  files); regression script lints clean too.
- **Decisions confirmed in code:** net-PnL (no escrow) — bankroll moves only at settlement;
  re-buy SETS bankroll to $100k (ledger delta records the top-up); `force` re-settle intentionally
  unsupported (would need PnL reversal).
- **Follow-ups (next slice):** idle-cash decay (matchday-level), the two formal leaderboards
  (bankroll + accuracy points), and real result ingestion to replace the manual `result` command.
  Consider seeding an `init` bankroll-ledger row at competitor creation so the ledger sums from $1M.
