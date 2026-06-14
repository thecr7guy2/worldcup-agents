import type { BoardEntry, TeamSide } from "@/lib/api";
import { outcomeLabel, pct } from "@/lib/format";

type Bucket = "home" | "draw" | "away";

// `winner` and `pick` arrive from the API as the OUTCOME literal — "home" | "draw"
// | "away" — not a team name. Bucket directly off that literal.
function bucketOf(outcome: string): Bucket {
  const w = outcome.trim().toLowerCase();
  if (w === "away") return "away";
  if (w === "draw" || w === "x") return "draw";
  return "home";
}

// Where the seven models split on a fixture, in two acts: who each model PREDICTED
// to win (odds hidden) and where each then put its MONEY (odds shown). The gap between
// the two columns is the point of the competition — a model can rate Turkey the likeliest
// winner yet bet the draw on price. Plus the confidence spread. Pure facts from the board.
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
  const total = preds.length;

  const rows: { key: Bucket; label: string }[] = [
    { key: "home", label: home.name },
    { key: "draw", label: "Draw" },
    { key: "away", label: away.name },
  ];

  // Act 1 — predicted winner (odds hidden).
  const predCount: Record<Bucket, number> = { home: 0, draw: 0, away: 0 };
  for (const e of preds) predCount[bucketOf(e.prediction!.winner)] += 1;

  // Act 2 — where the money went (odds shown). Passes tracked separately.
  const betCount: Record<Bucket, number> = { home: 0, draw: 0, away: 0 };
  let passes = 0;
  let betsPlaced = 0;
  for (const e of entries) {
    if (!e.bet) continue;
    if (e.bet.pick && e.bet.stake > 0) {
      betCount[bucketOf(e.bet.pick)] += 1;
      betsPlaced += 1;
    } else {
      passes += 1;
    }
  }
  const anyBets = betsPlaced + passes > 0;

  const predWays = rows.filter((r) => predCount[r.key] > 0).length;
  const topPred = Math.max(...rows.map((r) => predCount[r.key]));
  const topBet = Math.max(...rows.map((r) => betCount[r.key]));
  const avgConf = preds.reduce((a, e) => a + e.prediction!.confidence, 0) / total;

  return (
    <section className="border-2 border-ink bg-surface p-5 shadow-[6px_6px_0_rgba(22,29,24,.12)] sm:p-6">
      <div className="mono mb-4 flex items-center justify-between text-[10px] uppercase tracking-[0.16em] text-faint">
        <span>Where the models split</span>
        <span>{predWays > 1 ? `${predWays}-way split` : "unanimous"}</span>
      </div>

      {/* legend: dark = blind prediction, accent = the actual bet */}
      <div className="mono mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[9px] uppercase tracking-[0.13em] text-faint">
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 bg-ink" /> Predicted · odds hidden
        </span>
        {anyBets && (
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-2.5 bg-volt" /> Bet · odds shown
          </span>
        )}
      </div>

      {/* per-outcome: a dark prediction bar and (below it) the accent money bar */}
      <div className="space-y-3">
        {rows.map((r) => (
          <div key={r.key} className="flex items-center gap-3">
            <span className="w-24 shrink-0 truncate text-sm font-semibold text-ink sm:w-28">
              {r.label}
            </span>
            <div className="flex-1 space-y-1">
              <TwinBar
                count={predCount[r.key]}
                total={total}
                isTop={predCount[r.key] === topPred}
                fill="var(--color-ink)"
              />
              {anyBets && (
                <TwinBar
                  count={betCount[r.key]}
                  total={total}
                  isTop={betCount[r.key] === topBet}
                  fill="var(--color-volt)"
                />
              )}
            </div>
          </div>
        ))}
      </div>

      {anyBets && passes > 0 && (
        <div className="mono mt-3 text-[10px] uppercase tracking-[0.14em] text-faint">
          {passes} {passes === 1 ? "model" : "models"} passed — no eligible price worth a bet
        </div>
      )}

      {/* confidence spread — each model's conviction in its own winner */}
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
              title={`${e.model}: ${pct(e.prediction!.confidence, 0)} on ${outcomeLabel(
                e.prediction!.winner,
                home.name,
                away.name,
              )}`}
            />
          ))}
          <span className="mono absolute -bottom-0 left-0 text-[9px] text-faint">0%</span>
          <span className="mono absolute -bottom-0 right-0 text-[9px] text-faint">100%</span>
        </div>
      </div>
    </section>
  );
}

function TwinBar({
  count,
  total,
  isTop,
  fill,
}: {
  count: number;
  total: number;
  isTop: boolean;
  fill: string;
}) {
  return (
    <div className="flex items-center gap-2.5">
      <div className="relative h-4 flex-1 overflow-hidden border border-line-strong bg-bg">
        <div
          className="h-full"
          style={{
            width: `${total ? (count / total) * 100 : 0}%`,
            background:
              count > 0 && isTop
                ? fill
                : `color-mix(in srgb, ${fill} 38%, transparent)`,
          }}
        />
      </div>
      <span className="mono w-9 shrink-0 text-right text-xs font-bold tabular-nums text-ink">
        {count}/{total}
      </span>
    </div>
  );
}
