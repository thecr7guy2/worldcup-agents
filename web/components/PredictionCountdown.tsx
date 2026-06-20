"use client";

import { useEffect, useState } from "react";

// Predictions are written when the orchestrator runs predict+bet, ~50 minutes before
// kickoff (config BET_LEAD_HOURS = 0.83h). The exact tick lands a few minutes either side
// of that, so every label here is deliberately phrased as an approximation, never a precise
// ticking clock. Once the lock window is reached we switch to a softer "almost here" state.
const LOCK_LEAD_MS = 50 * 60 * 1000;

function approxPhrase(ms: number): string {
  const minutes = ms / 60000;
  if (minutes >= 36 * 60) return `in about ${Math.round(minutes / (60 * 24))} days`;
  if (minutes >= 90) return `in about ${Math.round(minutes / 60)} hours`;
  if (minutes >= 45) return "in about an hour";
  if (minutes >= 10) return `in about ${Math.round(minutes / 5) * 5} minutes`;
  return "in a few minutes";
}

export function PredictionCountdown({ kickoff }: { kickoff: string }) {
  const lockAt = new Date(kickoff).getTime() - LOCK_LEAD_MS;
  // Time is resolved only after mount so the server and client render the same initial markup
  // (no hydration mismatch from Date.now()).
  const [now, setNow] = useState<number | null>(null);

  useEffect(() => {
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(id);
  }, []);

  if (now === null) return null;

  const remaining = lockAt - now;

  if (remaining <= 0) {
    return (
      <span className="mono mt-3 inline-flex items-center gap-2 border border-volt bg-volt/10 px-3 py-1.5 text-[11px] font-bold uppercase tracking-[0.12em] text-ink">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-volt" />
        Predictions almost here — refresh shortly
      </span>
    );
  }

  return (
    <span className="mono mt-3 inline-flex items-center gap-2 border border-line-strong bg-bg px-3 py-1.5 text-[11px] uppercase tracking-[0.12em] text-muted">
      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-volt" />
      Predictions expected {approxPhrase(remaining)}
      <span className="text-faint">· approx.</span>
    </span>
  );
}
