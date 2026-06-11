import { GlobeHemisphereWest } from "@phosphor-icons/react/dist/ssr";
import type { GeoSummary } from "@/lib/api";
import { Flag } from "@/components/Flag";
import { CountUp } from "@/components/CountUp";

// Public audience widget — "who's watching, and from where". Unique watchers counted by
// first-party cookie; per-country bars from the visitor's coarse geography. Unknown geography
// (geo lookup failed / private network) folds into one bucket and sorts last.

export function GeoWidget({ summary }: { summary: GeoSummary }) {
  const known = summary.countries.filter((c) => c.code);
  const unknown = summary.countries.find((c) => !c.code);
  const top = known.slice(0, 12);
  const restCount = known.slice(12).reduce((n, c) => n + c.count, 0);
  const max = Math.max(1, ...known.map((c) => c.count));

  return (
    <div className="border-2 border-ink bg-surface shadow-[7px_7px_0_rgba(22,29,24,.12)]">
      <div className="grid gap-6 p-6 sm:grid-cols-[auto_1fr] sm:items-center sm:gap-10 sm:p-8">
        <div className="flex items-center gap-4">
          <span className="grid h-14 w-14 shrink-0 place-items-center border-2 border-ink bg-volt text-surface">
            <GlobeHemisphereWest size={30} weight="bold" />
          </span>
          <div>
            <CountUp
              value={summary.total}
              format="int"
              className="block font-display text-4xl font-extrabold tabular-nums leading-none text-ink sm:text-5xl"
            />
            <div className="mono mt-1 text-[11px] uppercase tracking-[0.16em] text-faint">
              {summary.total === 1 ? "watcher" : "watchers"} ·{" "}
              {known.length} {known.length === 1 ? "country" : "countries"}
            </div>
          </div>
        </div>

        {top.length > 0 ? (
          <ul className="grid gap-x-8 gap-y-2.5 sm:grid-cols-2">
            {top.map((c) => (
              <li key={c.code} className="flex items-center gap-3">
                <Flag iso={c.code!.toLowerCase()} name={c.name} code={c.code} h={16} />
                <span className="w-28 shrink-0 truncate text-sm text-ink" title={c.name}>
                  {c.name}
                </span>
                <span className="relative h-2 flex-1 overflow-hidden bg-elevated">
                  <span
                    className="absolute inset-y-0 left-0 bg-volt"
                    style={{ width: `${(c.count / max) * 100}%` }}
                  />
                </span>
                <span className="mono w-7 shrink-0 text-right text-[12px] tabular-nums text-muted">
                  {c.count}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">
            No watchers logged yet — you might be the first to tune in.
          </p>
        )}
      </div>

      {(restCount > 0 || unknown) && (
        <div className="mono flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line px-6 py-3 text-[11px] uppercase tracking-[0.14em] text-faint sm:px-8">
          {restCount > 0 && <span>+{restCount} from other countries</span>}
          {unknown && <span>{unknown.count} unidentified</span>}
        </div>
      )}
    </div>
  );
}
