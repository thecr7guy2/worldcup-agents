"use client";

import { useMemo } from "react";

export interface PulseDay {
  date: string;
  group: number;
  knockout: number;
  isNext: boolean;
}

function shortDate(date: string): string {
  return new Date(`${date}T00:00:00Z`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

function longDate(date: string): string {
  return new Date(`${date}T00:00:00Z`).toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    timeZone: "UTC",
  });
}

export function TournamentPulse({ days }: { days: PulseDay[] }) {
  const stats = useMemo(() => {
    const group = days.reduce((sum, day) => sum + day.group, 0);
    const knockout = days.reduce((sum, day) => sum + day.knockout, 0);
    const peak = Math.max(1, ...days.map((day) => day.group + day.knockout));
    return { group, knockout, peak };
  }, [days]);

  if (days.length === 0) return null;

  return (
    <div className="overflow-hidden border-2 border-ink bg-surface shadow-[7px_7px_0_rgba(22,29,24,.12)]">
      <div className="grid border-b-2 border-ink sm:grid-cols-[1fr_auto]">
        <div className="p-5 sm:p-6">
          <div className="mono text-[10px] uppercase tracking-[0.18em] text-faint">
            Tournament workload / UTC
          </div>
          <p className="mt-2 max-w-[62ch] text-sm leading-relaxed text-muted">
            Group days arrive in dense waves. Knockout rounds slow the calendar down, but
            every call carries more weight because one match can end a team&apos;s tournament.
          </p>
        </div>
        <div className="grid grid-cols-3 border-t-2 border-ink sm:border-l-2 sm:border-t-0">
          <PulseStat label="Matchdays" value={days.length} />
          <PulseStat label="Peak load" value={`${stats.peak}/day`} />
          <PulseStat label="Final" value={shortDate(days[days.length - 1].date)} />
        </div>
      </div>

      <div className="overflow-x-auto p-5 sm:p-7">
        <div className="min-w-[980px]">
          <div className="flex h-64 items-end gap-1.5 border-b-2 border-ink px-1">
            {days.map((day, index) => {
              const total = day.group + day.knockout;
              const height = Math.max(18, (total / stats.peak) * 214);
              const showLabel =
                index === 0 ||
                index === days.length - 1 ||
                day.isNext ||
                index % 4 === 0;

              return (
                <div
                  key={day.date}
                  className="group relative flex h-full min-w-0 flex-1 items-end justify-center"
                  title={`${longDate(day.date)}: ${total} match${total === 1 ? "" : "es"}`}
                  aria-label={`${longDate(day.date)}, ${total} matches`}
                >
                  {day.isNext && (
                    <span className="absolute inset-x-0 bottom-0 top-3 border-x-2 border-t-2 border-volt bg-volt/5" />
                  )}
                  <div
                    className="relative z-10 flex w-full max-w-7 flex-col-reverse border-x border-t border-ink transition-transform group-hover:-translate-y-1"
                    style={{ height }}
                  >
                    {day.group > 0 && (
                      <span
                        className="block bg-ink"
                        style={{ height: `${(day.group / total) * 100}%` }}
                      />
                    )}
                    {day.knockout > 0 && (
                      <span
                        className="block bg-volt"
                        style={{ height: `${(day.knockout / total) * 100}%` }}
                      />
                    )}
                  </div>
                  <span className="mono absolute -bottom-6 left-1/2 -translate-x-1/2 whitespace-nowrap text-[8px] uppercase tracking-[-0.03em] text-faint">
                    {showLabel ? shortDate(day.date) : ""}
                  </span>
                  {day.isNext && (
                    <span className="mono absolute top-1 left-1/2 -translate-x-1/2 whitespace-nowrap bg-volt px-1.5 py-0.5 text-[8px] font-bold uppercase tracking-[0.12em] text-surface">
                      Next
                    </span>
                  )}
                </div>
              );
            })}
          </div>

          <div className="mt-9 flex flex-wrap items-center justify-between gap-4">
            <div className="mono flex flex-wrap gap-5 text-[10px] uppercase tracking-[0.14em] text-muted">
              <span className="flex items-center gap-2">
                <span className="h-3 w-3 bg-ink" />
                Group stage / {stats.group}
              </span>
              <span className="flex items-center gap-2">
                <span className="h-3 w-3 bg-volt" />
                Knockout / {stats.knockout}
              </span>
            </div>
            <span className="mono text-[9px] uppercase tracking-[0.14em] text-faint">
              Bar height = matches that day
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

function PulseStat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="min-w-24 border-r border-line-strong p-4 text-center last:border-r-0 sm:p-5">
      <div className="mono text-[9px] uppercase tracking-[0.14em] text-faint">{label}</div>
      <div className="mono mt-1 text-lg font-bold tabular-nums text-ink">{value}</div>
    </div>
  );
}
