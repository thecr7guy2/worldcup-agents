import type { BoardEntry, TeamSide } from "@/lib/api";
import { pct } from "@/lib/format";

type Bucket = "home" | "draw" | "away";

function bucketOf(winner: string, home: TeamSide, away: TeamSide): Bucket {
  const w = winner.trim().toLowerCase();
  if (w === "draw" || w === "x") return "draw";
  if ([away.name, away.code].some((v) => v && v.toLowerCase() === w)) return "away";
  return "home";
}

// Where the seven models split on a fixture: the pick distribution (how many
// backed home / draw / away) and the confidence spread (each model's conviction
// on a shared track). Pure facts from the board — renders once predictions lock.
export function Disagreement({
  entries,
  home,
  away,
}: {
  entries: BoardEntry[];
  home: TeamSide;
  away: TeamSide;
}) {
  const preds = entries.filter((e) => e.prediction != null);
  if (preds.length === 0) return null;

  const rows: { key: Bucket; label: string; count: number; confs: number[] }[] = [
    { key: "home", label: home.name, count: 0, confs: [] },
    { key: "draw", label: "Draw", count: 0, confs: [] },
    { key: "away", label: away.name, count: 0, confs: [] },
  ];
  for (const e of preds) {
    const b = bucketOf(e.prediction!.winner, home, away);
    const row = rows.find((r) => r.key === b)!;
    row.count += 1;
    row.confs.push(e.prediction!.confidence);
  }
  const total = preds.length;
  const top = Math.max(...rows.map((r) => r.count));
  const split = rows.filter((r) => r.count > 0).length > 1;
  const allConf = preds.map((e) => e.prediction!.confidence);
  const avgConf = allConf.reduce((a, b) => a + b, 0) / total;

  return (
    <section className="border-2 border-ink bg-surface p-5 shadow-[6px_6px_0_rgba(22,29,24,.12)] sm:p-6">
      <div className="mono mb-4 flex items-center justify-between text-[10px] uppercase tracking-[0.16em] text-faint">
        <span>Where the models split</span>
        <span>{split ? `${rows.filter((r) => r.count > 0).length}-way split` : "unanimous"}</span>
      </div>

      {/* pick distribution */}
      <div className="space-y-2.5">
        {rows.map((r) => (
          <div key={r.key} className="flex items-center gap-3">
            <span className="w-28 shrink-0 truncate text-sm font-semibold text-ink">{r.label}</span>
            <div className="relative h-6 flex-1 overflow-hidden border border-line-strong bg-bg">
              <div
                className="h-full"
                style={{
                  width: `${total ? (r.count / total) * 100 : 0}%`,
                  background: r.count === top && r.count > 0 ? "var(--color-ink)" : "color-mix(in srgb, var(--color-ink) 42%, transparent)",
                }}
              />
            </div>
            <span className="mono w-14 shrink-0 text-right text-sm font-bold tabular-nums text-ink">
              {r.count}/{total}
            </span>
          </div>
        ))}
      </div>

      {/* confidence spread */}
      <div className="mt-6 border-t border-line pt-4">
        <div className="mono mb-3 flex items-center justify-between text-[9px] uppercase tracking-[0.14em] text-faint">
          <span>Confidence spread</span>
          <span>avg {pct(avgConf, 0)}</span>
        </div>
        <div className="relative h-9">
          <div className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-line-strong" />
          {preds.map((e) => (
            <span
              key={e.model}
              className="absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface"
              style={{
                left: `${e.prediction!.confidence * 100}%`,
                background: e.meta.color,
              }}
              title={`${e.model}: ${pct(e.prediction!.confidence, 0)} on ${e.prediction!.winner}`}
            />
          ))}
          <span className="mono absolute -bottom-0 left-0 text-[9px] text-faint">0%</span>
          <span className="mono absolute -bottom-0 right-0 text-[9px] text-faint">100%</span>
        </div>
      </div>
    </section>
  );
}
