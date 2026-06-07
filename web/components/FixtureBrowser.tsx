"use client";

import { useMemo, useState } from "react";
import type { Fixture } from "@/lib/api";
import { MatchCard } from "./MatchCard";

const FILTERS: { key: string; label: string }[] = [
  { key: "all", label: "All" },
  { key: "group", label: "Groups" },
  { key: "round_of_32", label: "R32" },
  { key: "round_of_16", label: "R16" },
  { key: "quarter_final", label: "QF" },
  { key: "semi_final", label: "SF" },
  { key: "final", label: "Final" },
];

function dateHeading(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    timeZone: "UTC",
  });
}

export function FixtureBrowser({ fixtures }: { fixtures: Fixture[] }) {
  const [stage, setStage] = useState("all");

  const groups = useMemo(() => {
    const filtered =
      stage === "all" ? fixtures : fixtures.filter((f) => f.stage === stage);
    const byDate = new Map<string, Fixture[]>();
    for (const f of filtered) {
      const key = new Date(f.kickoff).toISOString().slice(0, 10);
      (byDate.get(key) ?? byDate.set(key, []).get(key)!).push(f);
    }
    return [...byDate.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [fixtures, stage]);

  return (
    <div>
      <div className="mb-8 flex flex-wrap gap-2">
        {FILTERS.map((f) => {
          const active = f.key === stage;
          const count =
            f.key === "all"
              ? fixtures.length
              : fixtures.filter((x) => x.stage === f.key).length;
          if (count === 0) return null;
          return (
            <button
              key={f.key}
              onClick={() => setStage(f.key)}
              className={`mono border px-3.5 py-1.5 text-xs font-medium uppercase tracking-wider transition-all ${
                active
                  ? "border-ink bg-ink text-surface shadow-[3px_3px_0_var(--color-volt)]"
                  : "border-line-strong bg-surface text-muted hover:border-ink hover:text-ink"
              }`}
            >
              {f.label}
              <span className={`ml-1.5 tabular-nums ${active ? "text-surface/60" : "text-faint"}`}>
                {count}
              </span>
            </button>
          );
        })}
      </div>

      <div className="flex flex-col gap-10">
        {groups.map(([date, matches]) => (
          <div key={date}>
            <div className="mb-3 flex items-center gap-3">
              <h3 className="font-display text-sm font-bold uppercase tracking-wide text-ink">
                {dateHeading(matches[0].kickoff)}
              </h3>
              <span className="h-px flex-1 bg-line" />
              <span className="mono text-[11px] text-faint">{matches.length} matches</span>
            </div>
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              {matches.map((fx) => (
                <MatchCard key={fx.id} fx={fx} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
