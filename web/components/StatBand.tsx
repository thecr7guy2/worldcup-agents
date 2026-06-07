import type { ReactNode } from "react";

// A row of headline metrics. Plain layout (no card boxes) per density guidance:
// numbers breathe, separated by hairlines.
export function StatBand({
  items,
}: {
  items: { label: string; value: ReactNode; sub?: string }[];
}) {
  return (
    <div className="grid grid-cols-2 border-y-2 border-ink bg-ink text-surface sm:grid-cols-3 lg:grid-cols-5">
      {items.map((it, i) => (
        <div key={it.label} className="relative border-b border-r border-white/15 px-4 py-5 last:border-r-0 lg:border-b-0">
          <span className="mono absolute right-2 top-2 text-[9px] text-surface/20">0{i + 1}</span>
          <div className="mono text-[9px] uppercase tracking-[0.18em] text-surface/45">
            {it.label}
          </div>
          <div className="mono mt-2 text-2xl font-bold tabular-nums text-surface">
            {it.value}
          </div>
          {it.sub && <div className="mt-1 text-[10px] uppercase tracking-wide text-surface/45">{it.sub}</div>}
        </div>
      ))}
    </div>
  );
}
