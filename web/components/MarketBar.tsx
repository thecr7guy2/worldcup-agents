import type { Fixture } from "@/lib/api";
import { impliedProbs, pct } from "@/lib/format";

// Market read: turns a fixture's decimal odds into a labelled implied-probability
// bar (home / draw / away). Monochrome by design so it never competes with the
// volt accent; segments are labelled so the shades are never ambiguous. Renders
// from live odds today — no kickoff required.
export function MarketBar({
  fx,
  compact = false,
}: {
  fx: Fixture;
  compact?: boolean;
}) {
  if (!fx.odds) return null;
  const p = impliedProbs(fx.odds);
  const segs = [
    { key: "home", label: fx.home.code ?? fx.home.name, value: p.home, shade: "var(--color-ink)" },
    { key: "draw", label: "Draw", value: p.draw, shade: "color-mix(in srgb, var(--color-ink) 32%, transparent)" },
    { key: "away", label: fx.away.code ?? fx.away.name, value: p.away, shade: "color-mix(in srgb, var(--color-ink) 62%, transparent)" },
  ];

  return (
    <div className={compact ? "" : "space-y-2"}>
      {!compact && (
        <div className="mono flex items-center justify-between text-[9px] uppercase tracking-[0.16em] text-faint">
          <span>Market implied probability</span>
          <span>{fx.odds.bookmaker} · {pct(p.overround, 1)} margin</span>
        </div>
      )}
      <div
        className={`flex w-full overflow-hidden border border-ink ${compact ? "h-2.5" : "h-7"}`}
        role="img"
        aria-label={`Implied probability: ${segs.map((s) => `${s.label} ${pct(s.value, 0)}`).join(", ")}`}
      >
        {segs.map((s) => (
          <div
            key={s.key}
            className="flex items-center justify-center overflow-hidden"
            style={{ width: `${s.value * 100}%`, background: s.shade }}
            title={`${s.label} ${pct(s.value, 0)}`}
          >
            {!compact && s.value > 0.13 && (
              <span className="mono truncate px-1 text-[10px] font-bold uppercase tracking-wide text-surface">
                {s.label} {pct(s.value, 0)}
              </span>
            )}
          </div>
        ))}
      </div>
      {!compact && (
        <div className="mono flex items-center justify-between text-[10px] tabular-nums text-muted">
          <span>{fx.home.name} {pct(p.home, 0)}</span>
          <span className="text-faint">Draw {pct(p.draw, 0)}</span>
          <span>{fx.away.name} {pct(p.away, 0)}</span>
        </div>
      )}
    </div>
  );
}
