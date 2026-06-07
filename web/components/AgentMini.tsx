import Link from "next/link";
import { ArrowUpRight } from "@phosphor-icons/react/dist/ssr";
import type { Competitor } from "@/lib/api";
import { money } from "@/lib/format";

// Compact roster teaser for the homepage. The full character card lives on
// /roster — this is just a clickable chip: kit-coloured sigil, model name,
// vendor, and live bankroll. Sized to fit all seven in two tidy rows.
export function AgentMini({ c, rank }: { c: Competitor; rank: number }) {
  const kit = c.meta.color;
  return (
    <Link
      href={`/agents/${encodeURIComponent(c.model)}`}
      className="group flex items-center gap-3 border-2 border-ink bg-surface p-3 transition-all duration-200 hover:-translate-y-1 hover:shadow-[5px_5px_0_var(--kit)]"
      style={{ ["--kit" as string]: kit }}
    >
      <span
        className="grid h-11 w-11 shrink-0 place-items-center font-display text-sm font-bold text-surface"
        style={{ background: kit }}
      >
        {c.meta.sigil}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate font-display text-base font-extrabold uppercase leading-none tracking-[-0.03em] text-ink">
          {c.model}
        </span>
        <span className="mono mt-1 block truncate text-[9px] uppercase tracking-[0.12em] text-faint">
          {c.meta.vendor} · {money(c.bankroll)}
        </span>
      </span>
      <span className="mono shrink-0 text-[9px] font-bold uppercase text-faint">#{rank}</span>
      <ArrowUpRight
        size={15}
        weight="bold"
        className="shrink-0 text-ink transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5"
      />
    </Link>
  );
}
