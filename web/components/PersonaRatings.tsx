import type { AgentMeta } from "@/lib/api";

const ORDER: Array<keyof AgentMeta["ratings"]> = [
  "VISION",
  "NERVE",
  "CHAOS",
  "VALUE",
  "MEMORY",
  "SWAG",
];

export function PersonaRatings({
  ratings,
  color,
  compact = false,
}: {
  ratings: AgentMeta["ratings"];
  color: string;
  compact?: boolean;
}) {
  if (compact) {
    return (
      <div className="grid grid-cols-3 gap-px border-y border-line bg-line">
        {ORDER.map((label) => (
          <div key={label} className="bg-surface px-2 py-2 text-center">
            <div className="mono text-base font-bold tabular-nums text-ink">{ratings[label]}</div>
            <div className="mono text-[8px] uppercase tracking-[0.12em] text-faint">{label}</div>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
      {ORDER.map((label) => (
        <div key={label}>
          <div className="mono flex items-center justify-between text-[10px] uppercase tracking-[0.14em] text-muted">
            <span>{label}</span>
            <span className="font-bold text-ink">{ratings[label]}</span>
          </div>
          <div className="mt-1.5 h-2 bg-elevated">
            <span
              className="block h-full"
              style={{ width: `${ratings[label]}%`, background: color }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
