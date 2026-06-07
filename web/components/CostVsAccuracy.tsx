"use client";

import {
  CartesianGrid,
  Cell,
  LabelList,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { pct } from "@/lib/format";

export interface CostPoint {
  model: string;
  color: string;
  cost: number; // billed USD
  hitRate: number; // 0..1
  tokens: number;
}

// Does the pricier model actually bet smarter? Each bubble is one model:
// x = billed compute cost, y = prediction hit rate, bubble size = tokens burned.
// The genuinely novel view on this dataset. Empty until telemetry exists.
export function CostVsAccuracy({ points }: { points: CostPoint[] }) {
  if (points.length === 0) return null;
  const data = points.map((p) => ({ ...p, y: Math.round(p.hitRate * 100) }));

  return (
    <div className="h-80 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 16, right: 24, bottom: 28, left: 8 }}>
          <CartesianGrid stroke="rgba(22,29,24,0.08)" />
          <XAxis
            type="number"
            dataKey="cost"
            name="Cost"
            tickFormatter={(v) => `$${v.toFixed(0)}`}
            tick={{ fill: "var(--color-faint)", fontSize: 11, fontFamily: "var(--font-mono)" }}
            label={{ value: "Compute cost (USD)", position: "insideBottom", offset: -14, fontSize: 11, fill: "var(--color-muted)" }}
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
          <ZAxis type="number" dataKey="tokens" range={[120, 900]} name="Tokens" />
          <Tooltip
            cursor={{ strokeDasharray: "3 3" }}
            contentStyle={{
              background: "#161d18",
              border: "1px solid rgba(255,255,255,0.16)",
              borderRadius: 8,
              fontSize: 12,
            }}
            formatter={(v: number, name: string) =>
              name === "Hit rate" ? [`${v}%`, name] : name === "Cost" ? [`$${v.toFixed(2)}`, name] : [v.toLocaleString(), name]
            }
          />
          <Scatter data={data} isAnimationActive>
            {data.map((d) => (
              <Cell key={d.model} fill={d.color} fillOpacity={0.85} stroke="var(--color-ink)" strokeWidth={1} />
            ))}
            <LabelList
              dataKey="model"
              position="top"
              style={{ fill: "var(--color-ink)", fontSize: 11, fontWeight: 700 }}
            />
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}
