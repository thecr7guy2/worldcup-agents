import type { ReactNode } from "react";

// Section heading — stacked (never the banned split-header pattern). Kicker is
// optional and rationed by the caller (taste-skill eyebrow restraint).
export function SectionHeading({
  title,
  sub,
  kicker,
  right,
}: {
  title: string;
  sub?: string;
  kicker?: string;
  right?: ReactNode;
}) {
  return (
    <div className="mb-7 grid gap-4 border-t-2 border-ink pt-3 sm:grid-cols-[1fr_auto] sm:items-end">
      <div className="flex items-start gap-3">
        <span className="mt-1.5 h-3 w-3 shrink-0 bg-volt" aria-hidden />
        <div>
        {kicker && (
          <div className="mono mb-1 text-[10px] uppercase tracking-[0.18em] text-muted">
            {kicker}
          </div>
        )}
        <h2 className="font-display text-3xl font-extrabold uppercase leading-none tracking-[-0.05em] text-ink sm:text-4xl">
          {title}
        </h2>
        {sub && <p className="mt-2 max-w-[64ch] text-sm leading-relaxed text-muted">{sub}</p>}
        </div>
      </div>
      {right}
    </div>
  );
}

export function Chip({
  children,
  tone = "default",
  className = "",
}: {
  children: ReactNode;
  tone?: "default" | "volt" | "down" | "muted";
  className?: string;
}) {
  const tones = {
    default: "border-line-strong text-muted",
    volt: "border-volt/30 bg-volt-dim text-volt",
    down: "border-down/30 bg-down-dim text-down",
    muted: "border-line text-faint",
  }[tone];
  return (
    <span
      className={`mono inline-flex items-center gap-1 border px-2 py-0.5 text-[11px] uppercase tracking-wider ${tones} ${className}`}
    >
      {children}
    </span>
  );
}

export function Stat({
  label,
  value,
  sub,
  tone = "ink",
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "ink" | "up" | "down" | "volt";
}) {
  const color = {
    ink: "text-ink",
    up: "text-up",
    down: "text-down",
    volt: "text-volt",
  }[tone];
  return (
    <div>
      <div className="mono text-[10px] uppercase tracking-[0.16em] text-faint">{label}</div>
      <div className={`mono mt-1 text-lg font-semibold tabular-nums ${color}`}>{value}</div>
      {sub && <div className="mt-0.5 text-[11px] text-muted">{sub}</div>}
    </div>
  );
}

// A card surface with the single locked radius. Optional accent stripe (kit color)
// stays inside the card, per the per-entity color rule.
export function Card({
  children,
  className = "",
  accent,
}: {
  children: ReactNode;
  className?: string;
  accent?: string;
}) {
  return (
    <div
      className={`relative overflow-hidden border border-line-strong bg-surface shadow-[6px_6px_0_rgba(22,29,24,0.12)] ${className}`}
    >
      {accent && (
        <span
          className="absolute inset-y-0 left-0 w-[5px]"
          style={{ background: accent }}
          aria-hidden
        />
      )}
      {children}
    </div>
  );
}
