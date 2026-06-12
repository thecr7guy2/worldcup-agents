"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export interface StepRow {
  model_name: string;
  step: string;
  cost_usd: number;
  tokens: number;
}

// Pipeline steps, in flow order, with a fixed colour each so the stack reads the
// same across models. predict/bet (the judgment steps) get the warm tones.
const STEP_ORDER: { key: string; label: string; color: string }[] = [
  { key: "intelligence", label: "Intelligence", color: "#161d18" },
  { key: "briefing", label: "Briefing", color: "#3c4a3f" },
  { key: "predict", label: "Predict", color: "#ef492f" },
  { key: "bet", label: "Bet", color: "#f2895f" },
  { key: "postmatch", label: "Post-match", color: "#8d8d7d" },
];

// Where the compute budget goes, per model, broken down by pipeline step.
// Empty until any model has run.
export function StepBreakdown({ rows }: { rows: StepRow[] }) {
  if (rows.length === 0) return null;
  const byModel = new Map<string, Record<string, number | string>>();
  for (const r of rows) {
    const m = byModel.get(r.model_name) ?? { model: r.model_name };
    m[r.step] = (Number(m[r.step] ?? 0) || 0) + r.cost_usd;
    byModel.set(r.model_name, m);
  }
  const data = Array.from(byModel.values());
  const present = STEP_ORDER.filter((s) => data.some((d) => d[s.key] != null));

  return (
    <div className="h-72 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
          <CartesianGrid stroke="rgba(22,29,24,0.08)" vertical={false} />
          <XAxis
            dataKey="model"
            tick={{ fill: "var(--color-muted)", fontSize: 11, fontWeight: 700 }}
            axisLine={{ stroke: "var(--color-line-strong)" }}
            tickLine={false}
            interval={0}
            angle={-12}
            textAnchor="end"
            height={48}
          />
          <YAxis
            // Spend is sub-dollar (cents of token cost), so whole-dollar ticks render
            // every gridline as "$0". Cent precision shows the real scale and still reads
            // as money once a model's cumulative cost climbs past $1 later in the run.
            tickFormatter={(v) => `$${Number(v).toFixed(2)}`}
            width={56}
            tick={{ fill: "var(--color-faint)", fontSize: 11, fontFamily: "var(--font-mono)" }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            cursor={{ fill: "rgba(22,29,24,0.05)" }}
            contentStyle={{
              background: "#161d18",
              border: "1px solid rgba(255,255,255,0.16)",
              borderRadius: 8,
              fontSize: 12,
            }}
            formatter={(v: number, name: string) => [`$${v.toFixed(3)}`, name]}
          />
          <Legend wrapperStyle={{ fontSize: 11, paddingTop: 6 }} />
          {present.map((s) => (
            <Bar key={s.key} dataKey={s.key} name={s.label} stackId="cost" fill={s.color} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
