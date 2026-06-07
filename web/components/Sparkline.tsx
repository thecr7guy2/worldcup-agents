"use client";

import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { BankrollPoint } from "@/lib/api";
import { money } from "@/lib/format";

// Bankroll-over-time area chart. Before any settlements the ledger is empty, so the
// caller renders an empty state instead of mounting this.
export function BankrollChart({
  history,
  starting,
  color,
}: {
  history: BankrollPoint[];
  starting: number;
  color: string;
}) {
  const data = [
    { i: 0, balance: starting, label: "Start" },
    ...history.map((h, idx) => ({
      i: idx + 1,
      balance: h.balance_after,
      label: h.reason,
    })),
  ];
  const min = Math.min(starting, ...data.map((d) => d.balance));
  const max = Math.max(starting, ...data.map((d) => d.balance));
  const pad = (max - min) * 0.15 || starting * 0.1;

  return (
    <div className="h-56 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
          <defs>
            <linearGradient id="bk" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.35} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis dataKey="i" hide />
          <YAxis
            domain={[min - pad, max + pad]}
            tickFormatter={(v) => money(v)}
            width={54}
            tick={{ fill: "#5c6a7a", fontSize: 11, fontFamily: "var(--font-mono)" }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            contentStyle={{
              background: "#12161d",
              border: "1px solid rgba(255,255,255,0.16)",
              borderRadius: 10,
              fontSize: 12,
            }}
            labelFormatter={() => ""}
            formatter={(v: number) => [money(v), "Bankroll"]}
          />
          <Area
            type="monotone"
            dataKey="balance"
            stroke={color}
            strokeWidth={2}
            fill="url(#bk)"
            dot={false}
            isAnimationActive
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
