"use client";

import { Warning, ArrowClockwise } from "@phosphor-icons/react";

export default function Error({ reset }: { error: Error; reset: () => void }) {
  return (
    <div className="flex min-h-[50dvh] flex-col items-center justify-center text-center">
      <span className="grid h-14 w-14 place-items-center bg-down text-surface">
        <Warning size={28} weight="bold" />
      </span>
      <h1 className="mt-5 font-display text-3xl font-extrabold uppercase tracking-[-0.05em] text-ink">The line dropped</h1>
      <p className="mt-2 max-w-[42ch] text-sm text-muted">
        We could not reach the competition data just now. The API may be restarting.
      </p>
      <button
        onClick={reset}
        className="mt-6 inline-flex items-center gap-2 border-2 border-ink bg-volt px-5 py-2.5 text-sm font-bold uppercase text-surface shadow-[4px_4px_0_var(--color-ink)] transition-transform hover:-translate-y-0.5 active:scale-[0.98]"
      >
        <ArrowClockwise size={16} weight="bold" /> Try again
      </button>
    </div>
  );
}
