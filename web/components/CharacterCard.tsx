import Link from "next/link";
import { ArrowUpRight, Coins, Cpu } from "@phosphor-icons/react/dist/ssr";
import type { Competitor } from "@/lib/api";
import { moneyFull, signedMoney, compact } from "@/lib/format";
import { BankrollBar } from "./BankrollBar";
import { CountUp } from "./CountUp";
import { PersonaEmblem } from "./PersonaEmblem";
import { PersonaRatings } from "./PersonaRatings";

export function CharacterCard({ c, rank }: { c: Competitor; rank?: number }) {
  const kit = c.meta.color;
  const profitUp = c.profit >= 0;

  return (
    <Link
      href={`/agents/${encodeURIComponent(c.model)}`}
      className="group relative block min-h-[570px] overflow-hidden border-2 border-ink bg-surface transition-all duration-200 hover:-translate-y-1.5 hover:shadow-[9px_9px_0_var(--kit)]"
      style={{ ["--kit" as string]: kit }}
    >
      <div
        className="relative min-h-[232px] overflow-hidden p-5 text-surface"
        style={{
          background: `linear-gradient(145deg, ${kit}, color-mix(in srgb, ${kit} 56%, #161d18))`,
        }}
      >
        <span className="pointer-events-none absolute -bottom-10 -right-2 font-display text-[12rem] font-extrabold leading-none text-white/10">
          {c.meta.squad_number}
        </span>
        <div className="relative flex items-start justify-between">
          <div>
            <div className="font-display text-5xl font-extrabold leading-none tracking-[-0.08em]">
              {c.meta.squad_number}
            </div>
            <div className="mono mt-1 max-w-[15ch] text-[9px] uppercase tracking-[0.16em] text-white/70">
              {c.meta.position}
            </div>
          </div>
          <div className="mono border border-white/35 px-2 py-1 text-[9px] uppercase tracking-[0.14em]">
            Self selected
          </div>
        </div>
        <PersonaEmblem
          meta={c.meta}
          size={76}
          className="absolute bottom-7 left-1/2 h-28 w-28 -translate-x-1/2 rotate-[-3deg] bg-surface/10 text-white backdrop-blur-sm transition-transform group-hover:rotate-3 group-hover:scale-105"
        />
        {rank != null && (
          <span className="mono absolute bottom-4 right-4 bg-ink px-2 py-1 text-[10px] font-bold text-surface">
            LIVE RANK #{rank}
          </span>
        )}
      </div>

      <div className="relative flex min-h-[338px] flex-col p-5">
        <div>
          <h3 className="font-display text-[1.7rem] font-extrabold uppercase leading-[0.92] tracking-[-0.055em] text-ink">
            {c.model}
          </h3>
          <div className="mono mt-2 flex flex-wrap gap-x-2 text-[10px] uppercase tracking-[0.14em] text-muted">
            <span>{c.meta.vendor}</span>
            <span className="text-faint">/</span>
            <span>{c.meta.position}</span>
          </div>
          <p className="mt-2 font-display text-sm font-bold italic text-muted">
            “{c.meta.tagline}”
          </p>
        </div>

        <div className="mt-4">
          <div className="mono mb-1.5 text-[8px] uppercase tracking-[0.16em] text-faint">
            Fictional player ratings
          </div>
          <PersonaRatings ratings={c.meta.ratings} color={kit} compact />
        </div>

        <div className="mt-4 grid grid-cols-2 gap-px bg-line">
          <FlavorCell label="Signature move" value={c.meta.signature_move} />
          <FlavorCell label="Fatal flaw" value={c.meta.weakness} />
        </div>

        <div className="mt-auto pt-5">
          <div className="flex items-end justify-between">
            <div>
              <div className="mono text-[8px] uppercase tracking-[0.16em] text-faint">Live bankroll</div>
              <CountUp
                value={c.bankroll}
                format="money"
                className="mono mt-1 block text-2xl font-bold tabular-nums text-ink"
              />
            </div>
            <span className={`mono text-xs font-semibold ${profitUp ? "text-up" : "text-down"}`}>
              {signedMoney(c.profit)}
            </span>
          </div>
          <div className="mt-2">
            <BankrollBar bankroll={c.bankroll} starting={c.starting_bankroll} />
          </div>
          <div className="mono mt-1 text-[9px] uppercase tracking-wider text-faint">
            {moneyFull(c.bankroll)}
          </div>

          <div className="mono mt-4 flex items-center justify-between border-t border-line pt-3 text-[9px] text-muted">
            <span className="inline-flex items-center gap-1">
              <Coins size={12} /> {c.bets_placed} bets
            </span>
            <span className="inline-flex items-center gap-1">
              <Cpu size={12} /> {c.telemetry.tokens ? compact(c.telemetry.tokens) : "0"} tok
            </span>
            <ArrowUpRight size={15} weight="bold" className="text-ink transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
          </div>
        </div>
      </div>
    </Link>
  );
}

function FlavorCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-bg px-3 py-2.5">
      <div className="mono text-[8px] uppercase tracking-[0.13em] text-faint">{label}</div>
      <div className="mt-1 text-[11px] font-semibold leading-tight text-ink">{value}</div>
    </div>
  );
}
