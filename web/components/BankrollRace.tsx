"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { money } from "@/lib/format";

export interface RaceModel {
  model: string;
  color: string;
  starting: number;
  current: number;
  history: { at: string; balance_after: number }[];
}

// Every competitor's bankroll on one axis — the headline "who's winning" race.
// Pre-kickoff all lines sit level at the starting bankroll (a clean starting
// grid); they diverge as bets settle. Handles the irregular per-model event
// timestamps by forward-filling each model's last known balance at every point.
export function BankrollRace({ models }: { models: RaceModel[] }) {
  const starting = models[0]?.starting ?? 1_000_000;
  const eventTimes = Array.from(
    new Set(models.flatMap((m) => m.history.map((h) => h.at))),
  ).sort();
  const started = eventTimes.length > 0;

  const balanceAt = (m: RaceModel, t: string) => {
    let bal = m.starting;
    for (const h of m.history) {
      if (h.at <= t) bal = h.balance_after;
      else break;
    }
    return bal;
  };

  const rows: Record<string, number | string>[] = [];
  rows.push(Object.fromEntries([["label", "Start"], ...models.map((m) => [m.model, m.starting])]));
  for (const t of eventTimes) {
    rows.push(
      Object.fromEntries([["label", t], ...models.map((m) => [m.model, balanceAt(m, t)])]),
    );
  }
  rows.push(Object.fromEntries([["label", "Now"], ...models.map((m) => [m.model, m.current])]));

  const allVals = rows.flatMap((r) => models.map((m) => r[m.model] as number));
  const min = Math.min(starting, ...allVals);
  const max = Math.max(starting, ...allVals);
  const pad = (max - min) * 0.12 || starting * 0.08;

  return (
    <div className="w-full">
      <div className="h-72 w-full sm:h-80">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 10, right: 16, bottom: 0, left: 8 }}>
            <CartesianGrid stroke="rgba(22,29,24,0.08)" vertical={false} />
            <XAxis dataKey="label" hide />
            <YAxis
              domain={[min - pad, max + pad]}
              tickFormatter={(v) => money(v)}
              width={56}
              tick={{ fill: "var(--color-faint)", fontSize: 11, fontFamily: "var(--font-mono)" }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip
              contentStyle={{
                background: "#161d18",
                border: "1px solid rgba(255,255,255,0.16)",
                borderRadius: 8,
                fontSize: 12,
              }}
              labelFormatter={() => ""}
              formatter={(v: number, name: string) => [money(v), name]}
            />
            <Legend
              iconType="plainline"
              wrapperStyle={{ fontSize: 11, paddingTop: 8 }}
            />
            {models.map((m) => (
              <Line
                key={m.model}
                type="monotone"
                dataKey={m.model}
                stroke={m.color}
                strokeWidth={2}
                dot={false}
                isAnimationActive
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      {!started && (
        <p className="mono mt-2 text-center text-[10px] uppercase tracking-[0.14em] text-faint">
          The race begins at kickoff — all seven level at {money(starting)}
        </p>
      )}
    </div>
  );
}
