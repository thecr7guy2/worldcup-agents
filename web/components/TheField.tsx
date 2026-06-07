import { Flag } from "@/components/Flag";

export interface FieldTeam {
  name: string;
  code: string | null;
  iso: string | null;
  rank: number | null;
}

export interface FieldGroup {
  letter: string;
  teams: FieldTeam[];
}

// The whole 2026 field on one board: every qualified nation drawn into its group.
// Static schedule data, so it renders identically before and after kickoff. The two
// teams of the next fixture are highlighted to tie the board to the hero ticket.
export function TheField({
  groups,
  highlight = [],
}: {
  groups: FieldGroup[];
  highlight?: string[];
}) {
  if (groups.length === 0) return null;
  const nations = groups.reduce((sum, group) => sum + group.teams.length, 0);
  const live = new Set(highlight);

  return (
    <div className="overflow-hidden border-2 border-ink bg-surface shadow-[7px_7px_0_rgba(22,29,24,.12)]">
      <div className="grid border-b-2 border-ink sm:grid-cols-[1fr_auto]">
        <div className="p-5 sm:p-6">
          <div className="mono text-[10px] uppercase tracking-[0.18em] text-faint">
            The field / {nations} nations · {groups.length} groups
          </div>
          <p className="mt-2 max-w-[62ch] text-sm leading-relaxed text-muted">
            Every nation that qualified, drawn into {groups.length} groups. The top two of
            each group plus the eight best third-placed teams reach the Round of 32 — from
            there it is sudden death all the way to the final.
          </p>
        </div>
        <div className="grid grid-cols-3 border-t-2 border-ink sm:border-l-2 sm:border-t-0">
          <FieldStat label="Nations" value={nations} />
          <FieldStat label="Groups" value={groups.length} />
          <FieldStat label="Advance" value="32" />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-px bg-line-strong sm:grid-cols-3 lg:grid-cols-4">
        {groups.map((group) => (
          <div key={group.letter} className="bg-surface p-4 sm:p-5">
            <div className="mb-3 flex items-baseline justify-between border-b border-ink pb-2">
              <span className="font-display text-lg font-extrabold uppercase tracking-[-0.04em] text-ink">
                Group {group.letter}
              </span>
              <span className="mono text-[9px] uppercase tracking-[0.14em] text-faint">
                {group.teams.length}
              </span>
            </div>
            <ul className="space-y-2">
              {group.teams.map((team) => {
                const isLive = live.has(team.name);
                return (
                  <li
                    key={team.name}
                    className={`flex items-center gap-2.5 ${
                      isLive ? "-mx-1 bg-volt px-1 py-0.5" : ""
                    }`}
                    title={isLive ? `${team.name} — next on the board` : team.name}
                  >
                    <Flag iso={team.iso} name={team.name} code={team.code} h={16} />
                    <span
                      className={`mono w-9 shrink-0 text-[10px] font-bold uppercase tracking-[0.04em] ${
                        isLive ? "text-surface" : "text-muted"
                      }`}
                    >
                      {team.code ?? team.name.slice(0, 3).toUpperCase()}
                    </span>
                    <span
                      className={`truncate text-sm font-semibold ${
                        isLive ? "text-surface" : "text-ink"
                      }`}
                    >
                      {team.name}
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}

function FieldStat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="min-w-24 border-r border-line-strong p-4 text-center last:border-r-0 sm:p-5">
      <div className="mono text-[9px] uppercase tracking-[0.14em] text-faint">{label}</div>
      <div className="mono mt-1 text-lg font-bold tabular-nums text-ink">{value}</div>
    </div>
  );
}
