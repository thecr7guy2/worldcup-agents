"use client";

import { useRouter } from "next/navigation";
import {
  Bar,
  BarChart,
  Cell,
  LabelList,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";

export interface FavoriteItem {
  fixtureId: number;
  label: string; // favored team
  opponent: string;
  prob: number; // 0..1 implied win probability
}

// Horizontal bar chart of the strongest favorites across upcoming fixtures,
// ranked by market-implied win probability. Pure facts (odds), so it renders
// fully today — no kickoff needed. Bars click through to the fixture.
export function MarketFavorites({ items }: { items: FavoriteItem[] }) {
  const router = useRouter();
  if (items.length === 0) return null;
  const data = items.map((it) => ({ ...it, value: Math.round(it.prob * 100) }));

  return (
    <div className="w-full" style={{ height: data.length * 46 + 16 }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 4, right: 44, bottom: 4, left: 4 }}
          barCategoryGap={9}
        >
          <XAxis type="number" domain={[0, 100]} hide />
          <YAxis
            type="category"
            dataKey="label"
            width={132}
            tick={{ fill: "var(--color-ink)", fontSize: 13, fontWeight: 700 }}
            axisLine={false}
            tickLine={false}
          />
          <Bar
            dataKey="value"
            radius={[0, 2, 2, 0]}
            isAnimationActive
            onClick={(d: { payload?: FavoriteItem }) =>
              d?.payload && router.push(`/fixtures/${d.payload.fixtureId}`)
            }
            className="cursor-pointer"
          >
            {data.map((d, i) => (
              <Cell key={d.fixtureId} fill={i === 0 ? "var(--color-volt)" : "var(--color-ink)"} />
            ))}
            <LabelList
              dataKey="value"
              position="right"
              formatter={(v: number) => `${v}%`}
              className="mono"
              style={{ fill: "var(--color-muted)", fontSize: 12, fontWeight: 700 }}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
