"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ChallengerLocked,
  challengerBet,
  challengerLogout,
  challengerPredict,
  challengerState,
  challengerUnlock,
  type ChallengerFixture,
  type ChallengerState,
} from "@/lib/api";
import { Card, Chip, SectionHeading, Stat } from "@/components/ui";

const money = (n: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(n);
const pct = (n: number) => `${Math.round(n * 100)}%`;
const SIDES = [
  { key: "home", label: "Home win" },
  { key: "draw", label: "Draw" },
  { key: "away", label: "Away win" },
] as const;

function kickoffLabel(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  }) + " UTC";
}

// ---- top-level console: gate -> standing + fixtures ----------------------

export function ChallengerConsole() {
  const [state, setState] = useState<ChallengerState | null>(null);
  const [locked, setLocked] = useState(false);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setState(await challengerState());
      setLocked(false);
    } catch (e) {
      if (e instanceof ChallengerLocked) setLocked(true);
      else throw e;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  if (loading) {
    return <p className="mono py-24 text-center text-sm text-faint">Decrypting…</p>;
  }
  if (locked || !state) {
    return <PassphraseGate onUnlocked={refresh} />;
  }

  const s = state.standing;
  const cap = s.bankroll * state.max_stake_fraction;
  const profitTone = s.profit > 0 ? "up" : s.profit < 0 ? "down" : "ink";

  return (
    <div>
      <SectionHeading
        kicker="Restricted · Human Challenger"
        title={`You vs. the Machines`}
        sub="You bet the same $1M bankroll on the same matches as the seven AIs, under the same rules — predict first (odds hidden), then stake. Bets lock ~50 minutes before kickoff. You are hidden from the public boards."
        right={
          <button
            onClick={() => challengerLogout().then(() => setLocked(true))}
            className="mono border border-line-strong px-3 py-1.5 text-[11px] uppercase tracking-wider text-muted hover:border-ink hover:text-ink"
          >
            Lock console
          </button>
        }
      />

      <Card accent="#c0392b" className="mb-10 p-6">
        <div className="grid grid-cols-2 gap-6 sm:grid-cols-3 lg:grid-cols-6">
          <Stat label="Bankroll" value={money(s.bankroll)} tone="ink" />
          <Stat label="Profit" value={`${s.profit >= 0 ? "+" : ""}${money(s.profit)}`} tone={profitTone} />
          <Stat label="Per-match cap" value={money(cap)} sub={pct(state.max_stake_fraction)} />
          <Stat label="Record" value={`${s.wins}-${s.losses}`} sub={`win rate ${pct(s.win_rate)}`} />
          <Stat
            label="Accuracy"
            value={`${s.accuracy.points} pts`}
            sub={`${s.accuracy.outcomes}/${s.accuracy.graded} outcomes`}
          />
          <Stat
            label="Lives"
            value={`${s.max_lives - s.lives_used}/${s.max_lives}`}
            sub={s.active ? "in the race" : "eliminated"}
            tone={s.active ? "ink" : "down"}
          />
        </div>
      </Card>

      <h3 className="font-display mb-4 text-sm font-bold uppercase tracking-wide text-ink">
        Open matches
        <span className="mono ml-2 text-[11px] text-faint">{state.open_fixtures.length} bettable</span>
      </h3>

      {state.open_fixtures.length === 0 ? (
        <p className="mono border border-dashed border-line-strong p-8 text-center text-sm text-faint">
          Nothing open right now — matches appear here once odds are posted and disappear ~50 min
          before kickoff.
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {state.open_fixtures.map((fx) => (
            <FixtureCard key={fx.fixture_id} fx={fx} cap={cap} onDone={refresh} />
          ))}
        </div>
      )}
    </div>
  );
}

// ---- passphrase gate -----------------------------------------------------

function PassphraseGate({ onUnlocked }: { onUnlocked: () => void }) {
  const [key, setKey] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      await challengerUnlock(key);
      onUnlocked();
    } catch {
      setErr("Wrong passphrase.");
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-md py-20">
      <Card accent="#c0392b" className="p-8">
        <div className="mono mb-2 text-[10px] uppercase tracking-[0.18em] text-muted">Restricted area</div>
        <h1 className="font-display text-2xl font-extrabold uppercase tracking-[-0.04em] text-ink">
          Challenger console
        </h1>
        <p className="mt-2 text-sm text-muted">Enter the passphrase to bet alongside the agents.</p>
        <form onSubmit={submit} className="mt-6 flex flex-col gap-3">
          <input
            type="password"
            autoFocus
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="Passphrase"
            className="mono border border-line-strong bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-ink"
          />
          {err && <p className="mono text-[11px] text-down">{err}</p>}
          <button
            type="submit"
            disabled={busy || !key}
            className="mono border border-ink bg-ink px-4 py-2 text-xs font-semibold uppercase tracking-wider text-surface shadow-[3px_3px_0_var(--color-volt)] disabled:opacity-40"
          >
            {busy ? "Checking…" : "Unlock"}
          </button>
        </form>
      </Card>
    </div>
  );
}

// ---- per-fixture card: locked bet | bet step | predict step --------------

function FixtureCard({
  fx,
  cap,
  onDone,
}: {
  fx: ChallengerFixture;
  cap: number;
  onDone: () => void;
}) {
  const title = `${fx.home} vs ${fx.away}`;
  return (
    <Card className="p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="font-display text-lg font-bold uppercase tracking-tight text-ink">{title}</div>
          <div className="mono mt-0.5 text-[11px] text-faint">
            {kickoffLabel(fx.kickoff)} · locks {kickoffLabel(fx.lock_at)}
          </div>
        </div>
        <Chip tone={fx.is_knockout ? "volt" : "muted"}>{fx.stage.replace(/_/g, " ")}</Chip>
      </div>

      {fx.bet ? (
        <PlacedBet fx={fx} />
      ) : fx.prediction ? (
        <BetStep fx={fx} cap={cap} onDone={onDone} />
      ) : (
        <PredictStep fx={fx} onDone={onDone} />
      )}
    </Card>
  );
}

function PlacedBet({ fx }: { fx: ChallengerFixture }) {
  const b = fx.bet!;
  const passed = b.pick === "pass";
  return (
    <div className="mt-4 border-t border-line pt-4">
      <div className="flex items-center gap-2">
        <Chip tone={passed ? "muted" : "volt"}>{passed ? "Passed" : `Bet: ${b.pick}`}</Chip>
        {!passed && (
          <span className="mono text-sm font-semibold text-ink">
            {money(b.stake)} {b.odds_at_bet ? `@ ${b.odds_at_bet.toFixed(2)}` : ""}
          </span>
        )}
        <span className="mono ml-auto text-[10px] uppercase tracking-wider text-faint">Locked in</span>
      </div>
      <p className="mono mt-2 text-[11px] text-muted">
        Predicted {fx.prediction?.winner} · confidence {pct(fx.prediction?.confidence ?? 0)}
      </p>
    </div>
  );
}

// step 1 — odds hidden
function PredictStep({ fx, onDone }: { fx: ChallengerFixture; onDone: () => void }) {
  const [winner, setWinner] = useState<string>("");
  const [conf, setConf] = useState(60);
  const [hg, setHg] = useState("");
  const [ag, setAg] = useState("");
  const [advances, setAdvances] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function submit() {
    if (!winner) return;
    setBusy(true);
    setErr("");
    try {
      await challengerPredict({
        fixture_id: fx.fixture_id,
        winner,
        confidence: conf / 100,
        home_goals: hg === "" ? null : Number(hg),
        away_goals: ag === "" ? null : Number(ag),
        advances: fx.is_knockout ? advances || null : null,
      });
      onDone();
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="mt-4 border-t border-line pt-4">
      <div className="mono mb-2 text-[10px] uppercase tracking-[0.16em] text-muted">
        Step 1 · Predict (odds hidden — use your own read)
      </div>
      <div className="flex flex-wrap gap-2">
        {SIDES.map((s) => (
          <button
            key={s.key}
            onClick={() => setWinner(s.key)}
            className={`mono border px-3 py-1.5 text-xs uppercase tracking-wider ${
              winner === s.key
                ? "border-ink bg-ink text-surface"
                : "border-line-strong text-muted hover:border-ink hover:text-ink"
            }`}
          >
            {s.label}
          </button>
        ))}
      </div>

      <label className="mono mt-4 block text-[10px] uppercase tracking-[0.16em] text-faint">
        Confidence: <span className="text-ink">{conf}%</span>
      </label>
      <input
        type="range"
        min={34}
        max={99}
        value={conf}
        onChange={(e) => setConf(Number(e.target.value))}
        className="mt-1 w-full accent-volt"
      />

      <div className="mt-3 flex flex-wrap items-end gap-3">
        <div>
          <label className="mono block text-[10px] uppercase tracking-[0.16em] text-faint">
            Most-likely score (optional)
          </label>
          <div className="mt-1 flex items-center gap-1">
            <input
              type="number"
              min={0}
              value={hg}
              onChange={(e) => setHg(e.target.value)}
              className="mono w-12 border border-line-strong bg-surface px-2 py-1 text-center text-sm text-ink outline-none focus:border-ink"
            />
            <span className="text-faint">–</span>
            <input
              type="number"
              min={0}
              value={ag}
              onChange={(e) => setAg(e.target.value)}
              className="mono w-12 border border-line-strong bg-surface px-2 py-1 text-center text-sm text-ink outline-none focus:border-ink"
            />
          </div>
        </div>
        {fx.is_knockout && (
          <div>
            <label className="mono block text-[10px] uppercase tracking-[0.16em] text-faint">
              Advances
            </label>
            <select
              value={advances}
              onChange={(e) => setAdvances(e.target.value)}
              className="mono mt-1 border border-line-strong bg-surface px-2 py-1 text-sm text-ink outline-none focus:border-ink"
            >
              <option value="">—</option>
              <option value="home">{fx.home}</option>
              <option value="away">{fx.away}</option>
            </select>
          </div>
        )}
      </div>

      {err && <p className="mono mt-3 text-[11px] text-down">{err}</p>}
      <button
        onClick={submit}
        disabled={busy || !winner || (fx.is_knockout && !advances)}
        className="mono mt-4 border border-ink bg-ink px-4 py-2 text-xs font-semibold uppercase tracking-wider text-surface shadow-[3px_3px_0_var(--color-volt)] disabled:opacity-40"
      >
        {busy ? "Saving…" : "Lock prediction → reveal odds"}
      </button>
    </div>
  );
}

// step 2 — odds shown
function BetStep({ fx, cap, onDone }: { fx: ChallengerFixture; cap: number; onDone: () => void }) {
  const [pick, setPick] = useState<string>("");
  const [stake, setStake] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const o = fx.odds;

  async function submit(asPass: boolean) {
    setBusy(true);
    setErr("");
    try {
      await challengerBet({
        fixture_id: fx.fixture_id,
        pick: asPass ? "pass" : pick,
        stake: asPass ? 0 : Number(stake || 0),
      });
      onDone();
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  }

  const overCap = Number(stake || 0) > cap;

  return (
    <div className="mt-4 border-t border-line pt-4">
      <div className="mono mb-1 text-[10px] uppercase tracking-[0.16em] text-muted">Step 2 · Bet (odds revealed)</div>
      <p className="mono mb-3 text-[11px] text-faint">
        Your call: <span className="text-ink">{fx.prediction?.winner}</span> · confidence{" "}
        {pct(fx.prediction?.confidence ?? 0)}
      </p>

      {o ? (
        <div className="mb-3 grid grid-cols-3 gap-2">
          {SIDES.map((s) => {
            const dec = (o as unknown as Record<string, number>)[s.key];
            return (
              <button
                key={s.key}
                onClick={() => setPick(s.key)}
                className={`mono border px-2 py-2 text-center text-xs uppercase tracking-wider ${
                  pick === s.key
                    ? "border-ink bg-ink text-surface"
                    : "border-line-strong text-muted hover:border-ink hover:text-ink"
                }`}
              >
                <div>{s.key}</div>
                <div className="mt-0.5 text-sm font-semibold tabular-nums">{dec.toFixed(2)}</div>
              </button>
            );
          })}
        </div>
      ) : (
        <p className="mono mb-3 text-[11px] text-down">Odds unavailable — you can still pass.</p>
      )}

      <label className="mono block text-[10px] uppercase tracking-[0.16em] text-faint">
        Stake (max {money(cap)})
      </label>
      <input
        type="number"
        min={0}
        value={stake}
        onChange={(e) => setStake(e.target.value)}
        placeholder="0"
        className={`mono mt-1 w-full border bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-ink ${
          overCap ? "border-down" : "border-line-strong"
        }`}
      />
      {overCap && <p className="mono mt-1 text-[11px] text-down">Above the 25% cap — will be clamped.</p>}
      {err && <p className="mono mt-2 text-[11px] text-down">{err}</p>}

      <div className="mt-4 flex gap-2">
        <button
          onClick={() => submit(false)}
          disabled={busy || !pick || !stake || Number(stake) <= 0}
          className="mono border border-ink bg-ink px-4 py-2 text-xs font-semibold uppercase tracking-wider text-surface shadow-[3px_3px_0_var(--color-volt)] disabled:opacity-40"
        >
          {busy ? "Placing…" : "Place bet"}
        </button>
        <button
          onClick={() => submit(true)}
          disabled={busy}
          className="mono border border-line-strong px-4 py-2 text-xs uppercase tracking-wider text-muted hover:border-ink hover:text-ink disabled:opacity-40"
        >
          Pass
        </button>
      </div>
    </div>
  );
}
