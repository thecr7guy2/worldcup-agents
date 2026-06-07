"use client";

import { motion, useReducedMotion } from "motion/react";

// HP-style bankroll bar: fill = bankroll vs starting (full at kickoff). Profit beyond
// starting is shown as a brighter "overcharge" cap; losses tint the bar toward red.
export function BankrollBar({
  bankroll,
  starting,
  height = 8,
}: {
  bankroll: number;
  starting: number;
  height?: number;
}) {
  const reduce = useReducedMotion();
  const ratio = bankroll / starting;
  const base = Math.max(0, Math.min(ratio, 1)); // 0..1 of starting
  const over = Math.max(0, Math.min(ratio - 1, 1)); // profit beyond starting
  const healthy = ratio >= 1;
  // interpolate color as health drops below starting
  const color = healthy
    ? "var(--color-volt)"
    : ratio > 0.5
      ? "#d7e25b"
      : "var(--color-down)";

  return (
    <div
      className="relative w-full overflow-hidden bg-elevated"
      style={{ height }}
    >
      <motion.span
        className="absolute inset-y-0 left-0"
        style={{ background: color, boxShadow: `0 0 16px ${color}66` }}
        initial={reduce ? false : { width: 0 }}
        whileInView={{ width: `${base * 100}%` }}
        viewport={{ once: true }}
        transition={{ duration: 0.9, ease: [0.16, 1, 0.3, 1] }}
      />
      {over > 0 && (
        <span
          className="absolute inset-y-0"
          style={{
            left: `${base * 100}%`,
            width: `${over * 100}%`,
            background:
              "repeating-linear-gradient(45deg, var(--color-volt), var(--color-volt) 4px, #161d18 4px, #161d18 8px)",
          }}
          aria-hidden
        />
      )}
    </div>
  );
}
