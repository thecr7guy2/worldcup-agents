"use client";

import {
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { Brain } from "@phosphor-icons/react/dist/ssr";

export interface CostPoint {
  model: string;
  color: string;
  cost: number; // billed USD
  hitRate: number; // 0..1
  tokens: number;
}

// Sub-dollar spend reads as "$0" rounded — show cents until the model crosses a dollar.
function costLabel(v: number): string {
  if (!v || v <= 0) return "$0";
  if (v < 1) return `${(v * 100).toFixed(1)}¢`;
  return v < 100 ? `$${v.toFixed(2)}` : `$${v.toFixed(0)}`;
}

interface Datum extends CostPoint {
  y: number;
}

function ChartTooltip({ active, payload }: { active?: boolean; payload?: { payload: Datum }[] }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="border border-white/15 bg-ink px-3 py-2 text-surface shadow-lg">
      <div className="mb-1 flex items-center gap-2 font-display text-sm font-bold">
        <span className="h-2.5 w-2.5" style={{ background: d.color }} />
        {d.model}
      </div>
      <dl className="mono grid grid-cols-[auto_auto] gap-x-3 gap-y-0.5 text-[11px] text-surface/70">
        <dt>Hit rate</dt>
        <dd className="text-right text-surface">{d.y}%</dd>
        <dt>Spend</dt>
        <dd className="text-right text-surface">{costLabel(d.cost)}</dd>
        <dt>Tokens</dt>
        <dd className="text-right text-surface">{d.tokens.toLocaleString()}</dd>
      </dl>
    </div>
  );
}

// Does the pricier model actually bet smarter? Each bubble is one model:
// x = billed compute cost, y = prediction hit rate, bubble size = tokens burned.
// Identity lives in the tooltip + legend (not always-on labels, which collide when models
// cluster at similar tiny costs). `accuracyReady` gates the flat pre-settlement state.
export function CostVsAccuracy({
  points,
  accuracyReady = true,
}: {
  points: CostPoint[];
  accuracyReady?: boolean;
}) {
  if (points.length === 0) return null;

  // Before any match settles every hit rate is 0 — a flat row of bubbles on the floor reads as
  // broken. Show an honest placeholder until results grade the first predictions.
  if (!accuracyReady) {
    return (
      <div className="flex h-80 w-full flex-col items-center justify-center gap-3 text-center">
        <span className="grid h-12 w-12 place-items-center border-2 border-ink bg-volt text-surface">
          <Brain size={24} weight="bold" />
        </span>
        <p className="font-display text-lg font-bold text-ink">Accuracy unlocks after the first match</p>
        <p className="max-w-[46ch] text-sm text-muted">
          All seven models have locked their opening bets. Hit rate is graded once results are
          final — this chart fills in as the tournament settles.
        </p>
        <div className="mono mt-1 flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-[11px] text-faint">
          {points.map((p) => (
            <span key={p.model} className="inline-flex items-center gap-1.5">
              <span className="h-2 w-2" style={{ background: p.color }} />
              {p.model} · {costLabel(p.cost)}
            </span>
          ))}
        </div>
      </div>
    );
  }

  const data: Datum[] = points.map((p) => ({ ...p, y: Math.round(p.hitRate * 100) }));

  return (
    <div className="w-full">
      <div className="h-80 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 16, right: 24, bottom: 28, left: 8 }}>
            <CartesianGrid stroke="rgba(22,29,24,0.08)" />
            <XAxis
              type="number"
              dataKey="cost"
              name="Cost"
              domain={[0, "dataMax"]}
              tickFormatter={costLabel}
              tick={{ fill: "var(--color-faint)", fontSize: 11, fontFamily: "var(--font-mono)" }}
              label={{ value: "Compute cost", position: "insideBottom", offset: -14, fontSize: 11, fill: "var(--color-muted)" }}
              axisLine={{ stroke: "var(--color-line-strong)" }}
              tickLine={false}
            />
            <YAxis
              type="number"
              dataKey="y"
              name="Hit rate"
              domain={[0, 100]}
              tickFormatter={(v) => `${v}%`}
              tick={{ fill: "var(--color-faint)", fontSize: 11, fontFamily: "var(--font-mono)" }}
              label={{ value: "Hit rate", angle: -90, position: "insideLeft", fontSize: 11, fill: "var(--color-muted)" }}
              axisLine={false}
              tickLine={false}
            />
            <ZAxis type="number" dataKey="tokens" range={[140, 900]} name="Tokens" />
            <Tooltip cursor={{ strokeDasharray: "3 3" }} content={<ChartTooltip />} />
            <Scatter data={data} isAnimationActive>
              {data.map((d) => (
                <Cell key={d.model} fill={d.color} fillOpacity={0.85} stroke="var(--color-ink)" strokeWidth={1} />
              ))}
            </Scatter>
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      {/* legend — identity without colliding on-bubble labels */}
      <div className="mono mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-line pt-3 text-[11px] text-muted">
        {data.map((d) => (
          <span key={d.model} className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5" style={{ background: d.color }} />
            {d.model}
          </span>
        ))}
      </div>
    </div>
  );
}
