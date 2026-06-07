"use client";

import { animate, useInView, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { money, moneyFull, compact } from "@/lib/format";

// Functions can't cross the server->client boundary, so the caller picks a formatter
// by name rather than passing one in.
const FORMATTERS: Record<string, (n: number) => string> = {
  money,
  moneyFull,
  compact,
  int: (n) => Math.round(n).toLocaleString("en-US"),
};

// Count-up number. Communicates magnitude (a bankroll racing up reads as "score").
// Honors reduced-motion by snapping to the final value.
export function CountUp({
  value,
  format = "int",
  className,
  duration = 1.2,
}: {
  value: number;
  format?: keyof typeof FORMATTERS | string;
  className?: string;
  duration?: number;
}) {
  const fmt = FORMATTERS[format] ?? FORMATTERS.int;
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, amount: 0.5 });
  const reduce = useReducedMotion();
  const [display, setDisplay] = useState(reduce ? value : 0);

  useEffect(() => {
    if (reduce) {
      setDisplay(value);
      return;
    }
    if (!inView) return;
    const controls = animate(0, value, {
      duration,
      ease: [0.16, 1, 0.3, 1],
      onUpdate: (v) => setDisplay(v),
    });
    return () => controls.stop();
  }, [inView, value, reduce, duration]);

  return (
    <span ref={ref} className={className}>
      {fmt(display)}
    </span>
  );
}
