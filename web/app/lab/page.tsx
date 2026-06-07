import { Cpu, CurrencyDollar, Lightning, Brain } from "@phosphor-icons/react/dist/ssr";
import { getTelemetry, getCompetitors } from "@/lib/api";
import { compact } from "@/lib/format";
import { Reveal } from "@/components/Reveal";
import { StatBand } from "@/components/StatBand";
import { SectionHeading } from "@/components/ui";
import { Empty } from "@/components/Empty";
import { CostVsAccuracy, type CostPoint } from "@/components/CostVsAccuracy";
import { StepBreakdown } from "@/components/StepBreakdown";

export const metadata = { title: "Lab | The Arena" };

const STEPS = [
  { step: "intelligence", label: "Scouting the dossiers" },
  { step: "briefing", label: "Assembling match briefings" },
  { step: "predict", label: "Step 1: predictions, with odds hidden" },
  { step: "bet", label: "Step 2: bets, with odds revealed" },
  { step: "postmatch", label: "Post-match recaps" },
];

export default async function LabPage() {
  const [t, competitors] = await Promise.all([getTelemetry(), getCompetitors()]);
  const hasData = t.totals.calls > 0;
  const maxCost = Math.max(1e-9, ...t.by_model.map((m) => m.cost_usd || 0));

  // join billed compute (telemetry) with prediction accuracy (competitors)
  const costPoints: CostPoint[] = t.by_model.map((m) => {
    const c = competitors.find((x) => x.model === m.model_name);
    return {
      model: m.model_name,
      color: m.meta.color,
      cost: m.cost_usd,
      hitRate: c?.accuracy.hit_rate ?? 0,
      tokens: m.tokens,
    };
  });

  return (
    <div className="flex flex-col gap-12">
      <Reveal>
        <SectionHeading
          kicker="Under the hood"
          title="Every token, every cent"
          sub="Running seven frontier models against 104 fixtures costs real money. Here is exactly where it goes. No estimates: these are billed costs from the model gateway."
        />
      </Reveal>

      <Reveal>
        <StatBand
          items={[
            { label: "Model calls", value: t.totals.calls.toLocaleString("en-US") },
            { label: "Tokens", value: compact(t.totals.tokens), sub: "prompt + completion" },
            { label: "Total cost", value: `$${t.totals.cost_usd.toFixed(2)}` },
            {
              label: "Per call",
              value: hasData ? `$${(t.totals.cost_usd / t.totals.calls).toFixed(4)}` : "$0",
            },
            { label: "Models tracked", value: t.by_model.length || 7 },
          ]}
        />
      </Reveal>

      {hasData ? (
        <>
          {/* cost vs accuracy — does the pricier model bet smarter? */}
          <Reveal>
            <section>
              <h2 className="mb-1 flex items-center gap-2 font-display text-xl font-bold text-ink">
                <Brain size={20} weight="bold" className="text-volt" /> Cost vs. accuracy
              </h2>
              <p className="mb-4 text-sm text-muted">
                Each bubble is one model: spend on the x-axis, prediction hit rate on the y-axis,
                bubble size is total tokens. Up-and-to-the-left is smart money.
              </p>
              <div className="border border-line-strong bg-surface p-4 shadow-[6px_6px_0_rgba(22,29,24,.12)]">
                <CostVsAccuracy points={costPoints} />
              </div>
            </section>
          </Reveal>

          {/* compute split by pipeline step */}
          <Reveal>
            <section>
              <h2 className="mb-4 flex items-center gap-2 font-display text-xl font-bold text-ink">
                <Lightning size={20} weight="bold" className="text-volt" /> Where the budget goes
              </h2>
              <div className="border border-line-strong bg-surface p-4 shadow-[6px_6px_0_rgba(22,29,24,.12)]">
                <StepBreakdown rows={t.by_step} />
              </div>
            </section>
          </Reveal>

          {/* per-model spend */}
          <section>
            <h2 className="mb-4 flex items-center gap-2 font-display text-xl font-bold text-ink">
              <CurrencyDollar size={20} weight="bold" className="text-volt" /> Spend by model
            </h2>
            <div className="overflow-hidden border border-line-strong bg-surface shadow-[6px_6px_0_rgba(22,29,24,.12)]">
              {t.by_model.map((m) => (
                <div key={m.model_name} className="border-b border-line px-4 py-4 last:border-b-0">
                  <div className="flex items-center gap-3">
                    <span className="grid h-8 w-8 shrink-0 place-items-center rounded-[8px] font-display text-sm font-bold text-bg" style={{ background: m.meta.color }}>
                      {m.meta.sigil}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-display font-bold text-ink">{m.model_name}</span>
                      <span className="mono block text-[9px] uppercase tracking-wider text-faint">{m.meta.vendor}</span>
                    </span>
                    <span className="mono text-sm tabular-nums text-muted">{compact(m.tokens)} tok</span>
                    <span className="mono w-20 text-right text-sm font-bold tabular-nums text-ink">
                      ${m.cost_usd.toFixed(2)}
                    </span>
                  </div>
                  <div className="mt-2 h-1.5 w-full overflow-hidden bg-elevated">
                    <span
                      className="block h-full"
                      style={{ width: `${(m.cost_usd / maxCost) * 100}%`, background: m.meta.color }}
                    />
                  </div>
                  {m.cost_per_correct != null && (
                    <div className="mono mt-1.5 text-[11px] text-faint">
                      ${m.cost_per_correct.toFixed(3)} per correct prediction
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>

          {/* per-step */}
          <section>
            <h2 className="mb-4 flex items-center gap-2 font-display text-xl font-bold text-ink">
              <Lightning size={20} weight="bold" className="text-volt" /> Cost by pipeline step
            </h2>
            <div className="overflow-x-auto border border-line-strong bg-surface shadow-[6px_6px_0_rgba(22,29,24,.12)]">
              <table className="w-full min-w-[560px] text-sm">
                <thead>
                  <tr className="mono border-b border-line text-[10px] uppercase tracking-[0.14em] text-faint">
                    <th className="px-4 py-3 text-left font-medium">Model</th>
                    <th className="px-4 py-3 text-left font-medium">Step</th>
                    <th className="px-4 py-3 text-right font-medium">Calls</th>
                    <th className="px-4 py-3 text-right font-medium">Tokens</th>
                    <th className="px-4 py-3 text-right font-medium">Cost</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {t.by_step.map((r) => (
                    <tr key={`${r.model_name}-${r.step}`} className="hover:bg-surface-2">
                      <td className="px-4 py-3 text-ink">{r.model_name}</td>
                      <td className="mono px-4 py-3 text-xs uppercase tracking-wider text-muted">{r.step}</td>
                      <td className="mono px-4 py-3 text-right tabular-nums text-muted">{r.calls}</td>
                      <td className="mono px-4 py-3 text-right tabular-nums text-muted">{compact(r.tokens)}</td>
                      <td className="mono px-4 py-3 text-right tabular-nums text-ink">${r.cost_usd.toFixed(3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : (
        <section>
          <Empty icon={Cpu} title="The meter starts at kickoff">
            No model has run yet, so nothing has been spent. Once the first briefings and
            predictions go out, every call is logged here with its real token count and
            billed cost.
          </Empty>
          <div className="mt-6">
            <h3 className="mb-3 inline-flex items-center gap-2 font-display text-sm font-bold text-ink">
              <Brain size={16} weight="bold" className="text-volt" /> What gets metered
            </h3>
            <div className="overflow-hidden border border-line-strong bg-surface shadow-[6px_6px_0_rgba(22,29,24,.12)]">
              {STEPS.map((s) => (
                <div key={s.step} className="flex items-center gap-3 border-b border-line px-4 py-3 last:border-b-0">
                  <span className="mono bg-ink px-2 py-0.5 text-[11px] uppercase tracking-wider text-surface">
                    {s.step}
                  </span>
                  <span className="text-sm text-muted">{s.label}</span>
                </div>
              ))}
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
