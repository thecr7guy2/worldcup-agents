import Link from "next/link";
import { CaretRight } from "@phosphor-icons/react/dist/ssr";
import type { Fixture } from "@/lib/api";
import { kickoffParts, stageShort, impliedProbs, pct } from "@/lib/format";
import { Flag } from "./Flag";

function TeamRow({
  side,
  goals,
  winner,
  odd,
  prob,
  isFav,
}: {
  side: Fixture["home"];
  goals: number | null;
  winner: boolean;
  odd: number | null;
  prob: number | null;
  isFav: boolean;
}) {
  return (
    <div className="flex items-center gap-2.5">
      <Flag iso={side.iso} name={side.name} code={side.code} h={20} />
      <span
        className={`min-w-0 flex-1 truncate text-sm ${
          winner || isFav ? "font-semibold text-ink" : "text-muted"
        }`}
      >
        {side.name}
      </span>
      {goals != null ? (
        <span
          className={`mono w-5 text-right text-sm font-bold tabular-nums ${
            winner ? "text-volt" : "text-muted"
          }`}
        >
          {goals}
        </span>
      ) : prob != null ? (
        <>
          {/* win-probability bar: the favourite is longer and darker */}
          <span className="hidden h-2 w-16 shrink-0 overflow-hidden bg-line sm:block">
            <span
              className="block h-full"
              style={{
                width: `${Math.max(prob * 100, 3)}%`,
                background: isFav ? "var(--color-ink)" : "var(--color-faint)",
              }}
            />
          </span>
          <span
            className={`mono w-8 shrink-0 text-right text-xs tabular-nums ${
              isFav ? "font-semibold text-ink" : "text-faint"
            }`}
          >
            {pct(prob, 0)}
          </span>
          {odd != null && (
            <span className="mono w-10 shrink-0 text-right text-xs tabular-nums text-muted">
              {odd.toFixed(2)}
            </span>
          )}
        </>
      ) : (
        odd != null && (
          <span className="mono w-10 shrink-0 text-right text-xs tabular-nums text-faint">
            {odd.toFixed(2)}
          </span>
        )
      )}
    </div>
  );
}

export function MatchCard({ fx }: { fx: Fixture }) {
  const k = kickoffParts(fx.kickoff);
  const finished = fx.status === "finished" && fx.result != null;
  const r = fx.result;
  const homeWin = r ? r.outcome === "home" : false;
  const awayWin = r ? r.outcome === "away" : false;

  const probs = !finished && fx.odds ? impliedProbs(fx.odds) : null;
  const homeFav = probs ? probs.home >= probs.away : false;

  return (
    <Link
      href={`/fixtures/${fx.id}`}
      className="group relative flex min-h-[116px] items-stretch border border-line-strong bg-surface transition-all duration-200 hover:-translate-y-1 hover:shadow-[6px_6px_0_var(--color-volt)]"
    >
      <div className="flex w-[76px] shrink-0 flex-col items-center justify-center border-r border-dashed border-line-strong bg-ink text-center text-surface">
        <span className="mono text-[9px] uppercase tracking-wider text-surface/45">{k.weekday}</span>
        <span className="font-display text-xl font-extrabold uppercase leading-none">{k.day}</span>
        <span className="mono mt-1 text-[10px] tabular-nums text-surface/65">{k.time}</span>
      </div>

      <div className="flex min-w-0 flex-1 flex-col justify-center gap-2.5 px-4 py-3">
        <TeamRow
          side={fx.home}
          goals={r?.home_goals ?? null}
          winner={homeWin}
          odd={fx.odds?.home ?? null}
          prob={probs ? probs.home : null}
          isFav={probs ? homeFav : false}
        />
        <TeamRow
          side={fx.away}
          goals={r?.away_goals ?? null}
          winner={awayWin}
          odd={fx.odds?.away ?? null}
          prob={probs ? probs.away : null}
          isFav={probs ? !homeFav : false}
        />
        {probs && (
          <div className="mono flex items-center gap-1.5 text-[9px] uppercase tracking-wider text-faint">
            <span className="hidden sm:inline">Win prob ·</span>
            <span>Draw {pct(probs.draw, 0)}</span>
          </div>
        )}
      </div>

      <div className="flex shrink-0 flex-col items-end justify-between p-3">
        <span className="mono border border-line-strong px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-muted">
          {fx.group ? `GRP ${fx.group}` : stageShort(fx.stage)}
        </span>
        {finished ? (
          <span className="mono text-[10px] uppercase tracking-wider text-faint">
            {r?.went_penalties ? "pens" : r?.went_extra_time ? "AET" : "FT"}
          </span>
        ) : (
          <CaretRight
            size={16}
            className="text-faint transition-transform group-hover:translate-x-1 group-hover:text-volt"
          />
        )}
      </div>
    </Link>
  );
}
