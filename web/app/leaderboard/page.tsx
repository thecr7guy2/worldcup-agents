import Link from "next/link";
import { Trophy, Target, Crosshair, Brain } from "@phosphor-icons/react/dist/ssr";
import { getBankrollBoard, getAccuracyBoard, getBrierBoard, getOverview, getCompetitor } from "@/lib/api";
import { money, signedMoney, signedPct, pct } from "@/lib/format";
import { Reveal } from "@/components/Reveal";
import { BankrollBar } from "@/components/BankrollBar";
import { BankrollRace, type RaceModel } from "@/components/BankrollRace";
import { SectionHeading } from "@/components/ui";
import { Empty } from "@/components/Empty";

export const metadata = { title: "Standings | The Arena" };

export default async function LeaderboardPage() {
  const [bankroll, accuracy, brier, overview] = await Promise.all([
    getBankrollBoard(),
    getAccuracyBoard(),
    // Degrade gracefully if the brier route isn't live yet (e.g. wc-api not yet
    // restarted after deploy): show the empty state, never crash the whole board.
    getBrierBoard().catch(() => ({ standings: [], baseline: 2 / 3 })),
    getOverview(),
  ]);
  const allTied = bankroll.every((c) => c.bankroll === bankroll[0].bankroll);

  // bankroll-over-time for every model, merged into one race chart
  const details = await Promise.all(bankroll.map((c) => getCompetitor(c.model)));
  const raceModels: RaceModel[] = details.map((d) => ({
    model: d.model,
    color: d.meta.color,
    starting: d.starting_bankroll,
    current: d.bankroll,
    history: d.bankroll_history.map((h) => ({ at: h.at, balance_after: h.balance_after })),
  }));

  return (
    <div className="flex flex-col gap-14">
      <Reveal>
        <SectionHeading
          kicker="Standings"
          title="Three ways to win"
          sub="Bankroll rewards the sharpest gambler. Accuracy rewards the most correct forecaster. Reasoning rewards the best-calibrated mind — graded on its probabilities before the odds are ever shown. They are rarely the same model."
        />
      </Reveal>

      {/* bankroll race — every model's balance on one axis */}
      <Reveal>
        <section className="border-2 border-ink bg-surface p-5 shadow-[7px_7px_0_rgba(22,29,24,.12)] sm:p-6">
          <div className="mono mb-4 flex items-center justify-between text-[10px] uppercase tracking-[0.16em] text-faint">
            <span>Bankroll race</span>
            <span>{overview.started ? "live" : "starting grid"}</span>
          </div>
          <BankrollRace models={raceModels} />
        </section>
      </Reveal>

      {/* bankroll board (primary) */}
      <section>
        <h2 className="mb-4 flex items-center gap-2 font-display text-xl font-bold text-ink">
          <Trophy size={20} weight="fill" className="text-volt" /> Bankroll
          <span className="mono text-[11px] font-normal uppercase tracking-[0.16em] text-faint">
            best gambler
          </span>
        </h2>

        {allTied && !overview.started && (
          <p className="mb-4 text-sm text-muted">
            Even money. Every competitor holds the full {money(overview.starting_bankroll)}{" "}
            starting stake until the first ball is kicked.
          </p>
        )}

        <div className="overflow-hidden border border-line-strong bg-surface shadow-[6px_6px_0_rgba(22,29,24,.12)]">
          {bankroll.map((c, i) => (
            <Reveal key={c.model} delay={i * 0.03}>
              <Link
                href={`/agents/${encodeURIComponent(c.model)}`}
                className={`flex items-center gap-4 border-b border-line px-4 py-4 transition-colors last:border-b-0 hover:bg-surface-2 ${
                  i === 0 ? "bg-volt-dim/40" : ""
                }`}
              >
                <span
                  className={`mono grid h-8 w-8 shrink-0 place-items-center rounded-[8px] text-sm font-bold tabular-nums ${
                    i === 0 ? "bg-volt text-bg" : "bg-elevated text-muted"
                  }`}
                >
                  {i + 1}
                </span>
                <span
                  className="grid h-9 w-9 shrink-0 place-items-center rounded-[9px] font-display text-base font-bold text-bg"
                  style={{ background: c.meta.color }}
                >
                  {c.meta.sigil}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate font-display font-bold text-ink">{c.model}</span>
                    <span className="mono hidden text-[10px] uppercase tracking-wider text-faint sm:inline">
                      {c.meta.vendor}
                    </span>
                  </div>
                  <div className="mt-1.5 max-w-xs">
                    <BankrollBar bankroll={c.bankroll} starting={c.starting_bankroll} height={6} />
                  </div>
                </div>
                <div className="hidden text-right sm:block">
                  <div className="mono text-[10px] uppercase tracking-wider text-faint">ROI</div>
                  <div className={`mono text-sm tabular-nums ${c.bets_placed ? (c.roi >= 0 ? "text-up" : "text-down") : "text-faint"}`}>
                    {c.bets_placed ? signedPct(c.roi) : "—"}
                  </div>
                </div>
                <div className="w-28 text-right">
                  <div className="mono text-base font-bold tabular-nums text-ink">{money(c.bankroll)}</div>
                  <div className={`mono text-xs tabular-nums ${c.profit >= 0 ? "text-up" : "text-down"}`}>
                    {signedMoney(c.profit)}
                  </div>
                </div>
              </Link>
            </Reveal>
          ))}
        </div>
      </section>

      {/* accuracy board (secondary) */}
      <section>
        <h2 className="mb-4 flex items-center gap-2 font-display text-xl font-bold text-ink">
          <Crosshair size={20} weight="bold" className="text-volt" /> Accuracy
          <span className="mono text-[11px] font-normal uppercase tracking-[0.16em] text-faint">
            best forecaster
          </span>
        </h2>

        {accuracy.length > 0 ? (
          <div className="overflow-x-auto border border-line-strong bg-surface shadow-[6px_6px_0_rgba(22,29,24,.12)]">
            <table className="w-full min-w-[640px] text-sm">
              <thead>
                <tr className="mono border-b border-line text-[10px] uppercase tracking-[0.14em] text-faint">
                  <th className="px-4 py-3 text-left font-medium">#</th>
                  <th className="px-4 py-3 text-left font-medium">Model</th>
                  <th className="px-4 py-3 text-right font-medium">Points</th>
                  <th className="px-4 py-3 text-right font-medium">Exact</th>
                  <th className="px-4 py-3 text-right font-medium">Outcomes</th>
                  <th className="px-4 py-3 text-right font-medium">Advancers</th>
                  <th className="px-4 py-3 text-right font-medium">Hit rate</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {accuracy.map((r, i) => (
                  <tr key={r.model} className={`hover:bg-surface-2 ${i === 0 ? "bg-volt-dim/40" : ""}`}>
                    <td className="mono px-4 py-3 tabular-nums text-muted">{i + 1}</td>
                    <td className="px-4 py-3">
                      <Link href={`/agents/${encodeURIComponent(r.model)}`} className="flex items-center gap-2 font-medium text-ink hover:text-volt">
                        <span className="grid h-7 w-7 place-items-center rounded-[7px] font-display text-sm font-bold text-bg" style={{ background: r.meta.color }}>
                          {r.meta.sigil}
                        </span>
                        <span>
                          <span className="block">{r.model}</span>
                          <span className="mono block text-[9px] uppercase text-faint">{r.meta.vendor}</span>
                        </span>
                      </Link>
                    </td>
                    <td className="mono px-4 py-3 text-right font-bold tabular-nums text-volt">{r.points}</td>
                    <td className="mono px-4 py-3 text-right tabular-nums text-muted">{r.exact}</td>
                    <td className="mono px-4 py-3 text-right tabular-nums text-muted">{r.outcomes}</td>
                    <td className="mono px-4 py-3 text-right tabular-nums text-muted">{r.advance}</td>
                    <td className="mono px-4 py-3 text-right tabular-nums text-muted">{pct(r.hit_rate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty icon={Target} title="No graded predictions yet">
            Accuracy is scored off each model&apos;s 90-minute call once results come in.
            The board fills in after the first matches finish.
          </Empty>
        )}
      </section>

      {/* reasoning board (Brier — calibration of the blind forecast) */}
      <section>
        <h2 className="mb-2 flex items-center gap-2 font-display text-xl font-bold text-ink">
          <Brain size={20} weight="bold" className="text-volt" /> Reasoning
          <span className="mono text-[11px] font-normal uppercase tracking-[0.16em] text-faint">
            best calibrated
          </span>
        </h2>
        <p className="mb-4 max-w-2xl text-sm text-muted">
          Lower is better. The Brier score measures how closely each model&apos;s 1X2
          probabilities matched what actually happened — graded on its blind Step-1 forecast,
          before it ever saw the odds, so it can&apos;t be gamed by following the market.{" "}
          <span className="mono text-faint">
            {brier.baseline.toFixed(3)} = no better than a 33/33/33 guess.
          </span>
        </p>

        {brier.standings.length > 0 ? (
          <div className="overflow-x-auto border border-line-strong bg-surface shadow-[6px_6px_0_rgba(22,29,24,.12)]">
            <table className="w-full min-w-[480px] text-sm">
              <thead>
                <tr className="mono border-b border-line text-[10px] uppercase tracking-[0.14em] text-faint">
                  <th className="px-4 py-3 text-left font-medium">#</th>
                  <th className="px-4 py-3 text-left font-medium">Model</th>
                  <th className="px-4 py-3 text-right font-medium">Brier</th>
                  <th className="px-4 py-3 text-right font-medium">Graded</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {brier.standings.map((r, i) => (
                  <tr key={r.model} className={`hover:bg-surface-2 ${i === 0 ? "bg-volt-dim/40" : ""}`}>
                    <td className="mono px-4 py-3 tabular-nums text-muted">{i + 1}</td>
                    <td className="px-4 py-3">
                      <Link href={`/agents/${encodeURIComponent(r.model)}`} className="flex items-center gap-2 font-medium text-ink hover:text-volt">
                        <span className="grid h-7 w-7 place-items-center rounded-[7px] font-display text-sm font-bold text-bg" style={{ background: r.meta.color }}>
                          {r.meta.sigil}
                        </span>
                        <span>
                          <span className="block">{r.model}</span>
                          <span className="mono block text-[9px] uppercase text-faint">{r.meta.vendor}</span>
                        </span>
                      </Link>
                    </td>
                    <td className="mono px-4 py-3 text-right font-bold tabular-nums text-volt">{r.brier.toFixed(3)}</td>
                    <td className="mono px-4 py-3 text-right tabular-nums text-muted">{r.graded}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="mono border-t border-line text-[11px] text-faint">
                  <td className="px-4 py-2.5" colSpan={2}>
                    Uniform 33/33/33 baseline
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums">{brier.baseline.toFixed(3)}</td>
                  <td className="px-4 py-2.5" />
                </tr>
              </tfoot>
            </table>
          </div>
        ) : (
          <Empty icon={Brain} title="No graded predictions yet">
            Reasoning is scored once results come in — each model&apos;s blind probability
            forecast is graded against what actually happened.
          </Empty>
        )}
      </section>
    </div>
  );
}
