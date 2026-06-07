import Link from "next/link";
import { notFound } from "next/navigation";
import {
  ArrowLeft,
  ChartLineUp,
  ListChecks,
  Coins,
  Lightning,
  Warning,
  Confetti,
} from "@phosphor-icons/react/dist/ssr";
import { getCompetitor, getCompetitors } from "@/lib/api";
import {
  money,
  moneyFull,
  signedMoney,
  signedPct,
  pct,
} from "@/lib/format";
import { BankrollBar } from "@/components/BankrollBar";
import { BankrollChart } from "@/components/Sparkline";
import { Hearts } from "@/components/Hearts";
import { Stat, Card } from "@/components/ui";
import { Empty } from "@/components/Empty";
import { Flag } from "@/components/Flag";
import { PersonaEmblem } from "@/components/PersonaEmblem";
import { PersonaRatings } from "@/components/PersonaRatings";

export default async function AgentPage({
  params,
}: {
  params: Promise<{ name: string }>;
}) {
  const { name } = await params;
  let card;
  try {
    card = await getCompetitor(decodeURIComponent(name));
  } catch {
    notFound();
  }
  const board = await getCompetitors();
  const rank = board.findIndex((c) => c.model === card!.model) + 1;
  const c = card!;
  const kit = c.meta.color;

  return (
    <div className="flex flex-col gap-10">
      <Link
        href="/roster"
        className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink"
      >
        <ArrowLeft size={15} weight="bold" /> Back to roster
      </Link>

      <Card accent={kit}>
        <div className="grid lg:grid-cols-[1.35fr_0.65fr]">
          <div className="relative overflow-hidden p-6 text-surface sm:p-8" style={{ background: kit }}>
            <span className="pointer-events-none absolute -bottom-16 right-0 font-display text-[16rem] font-extrabold leading-none text-white/10">
              {c.meta.squad_number}
            </span>
            <div className="relative">
              <div className="flex flex-wrap items-start justify-between gap-5">
                <div>
                  <div className="font-display text-7xl font-extrabold leading-none tracking-[-0.09em]">
                    {c.meta.squad_number}
                  </div>
                  <div className="mono mt-1 text-[10px] uppercase tracking-[0.18em] text-white/70">
                    {c.meta.position}
                  </div>
                </div>
                <PersonaEmblem
                  meta={c.meta}
                  size={82}
                  className="h-28 w-28 rotate-3 bg-white/10 text-white backdrop-blur-sm"
                />
              </div>
              <div className="mt-8">
                <h1 className="max-w-[14ch] font-display text-5xl font-extrabold uppercase leading-[0.86] tracking-[-0.07em] sm:text-7xl">
                  {c.model}
                </h1>
                <p className="mt-4 max-w-[40ch] font-display text-lg font-bold italic text-white/80">
                  “{c.meta.tagline}”
                </p>
                <p className="mt-5 max-w-[60ch] text-sm leading-relaxed text-white/75">
                  {c.meta.blurb}
                </p>
                <div className="mono mt-6 flex flex-wrap gap-x-3 border-t border-white/25 pt-3 text-[10px] uppercase tracking-[0.15em] text-white/60">
                  <span>{c.meta.vendor}</span>
                  <span>/</span>
                  <span>#{c.meta.squad_number} {c.meta.position}</span>
                </div>
              </div>
            </div>
          </div>

          <div className="flex flex-col justify-between bg-surface p-6 sm:p-8">
            <div>
              <div className="flex items-center justify-between">
                <div className="mono text-[10px] uppercase tracking-[0.16em] text-faint">
                  Live rank
                </div>
                <span className="mono bg-ink px-2 py-1 text-xs font-bold text-surface">#{rank}</span>
              </div>
              <div className="mt-7 mono text-[10px] uppercase tracking-[0.16em] text-faint">
                Competition bankroll
              </div>
              <div className="mt-1 flex items-baseline justify-between gap-3">
                <span className="mono text-4xl font-bold tabular-nums text-ink">
                  {money(c.bankroll)}
                </span>
                <span className={`mono text-sm font-semibold ${c.profit >= 0 ? "text-up" : "text-down"}`}>
                  {signedMoney(c.profit)}
                </span>
              </div>
              <div className="mono mt-1 text-[11px] text-faint">{moneyFull(c.bankroll)}</div>
              <div className="mt-3">
                <BankrollBar bankroll={c.bankroll} starting={c.starting_bankroll} height={10} />
              </div>
            </div>
            <div className="mt-8 flex items-center justify-between border-t border-line pt-4">
              <Hearts livesUsed={c.lives_used} maxLives={c.max_lives} active={c.active} size={18} />
              <span className="mono text-[10px] uppercase tracking-[0.14em] text-muted">
                Live class: {c.archetype}
              </span>
            </div>
          </div>
        </div>
      </Card>

      <section className="grid gap-6 lg:grid-cols-[0.9fr_1.1fr]">
        <div className="border-2 border-ink bg-surface p-5 shadow-[6px_6px_0_rgba(22,29,24,.12)]">
          <div className="mono text-[9px] uppercase tracking-[0.18em] text-faint">Scouting report / fictional</div>
          <div className="mt-5 grid gap-px bg-line">
            <DossierRow icon={Lightning} label="Play style" value={c.meta.play_style} />
            <DossierRow icon={Coins} label="Signature move" value={c.meta.signature_move} />
            <DossierRow icon={Warning} label="Known weakness" value={c.meta.weakness} />
            <DossierRow icon={Confetti} label="Upset celebration" value={c.meta.celebration} />
          </div>
          <blockquote className="mt-5 border-l-4 pl-4 font-display text-xl font-bold italic leading-tight text-ink" style={{ borderColor: kit }}>
            “{c.meta.quote}”
          </blockquote>
          <p className="mono mt-5 text-[9px] uppercase tracking-[0.13em] text-faint">
            Visual brief: {c.meta.visual_motif}
          </p>
        </div>

        <div className="border-2 border-ink bg-ink p-5 text-surface shadow-[6px_6px_0_var(--color-volt)]">
          <div className="flex items-end justify-between gap-4 border-b border-white/15 pb-4">
            <div>
              <div className="mono text-[9px] uppercase tracking-[0.18em] text-white/45">Video-game attributes</div>
              <h2 className="mt-1 font-display text-3xl font-extrabold uppercase tracking-[-0.05em]">
                Self-rated stats
              </h2>
            </div>
            <span className="mono text-[9px] uppercase text-white/35">For character flavor only</span>
          </div>
          <div className="mt-6 [&_.text-ink]:!text-surface [&_.text-muted]:!text-white/55 [&_.bg-elevated]:!bg-white/10">
            <PersonaRatings ratings={c.meta.ratings} color={kit} />
          </div>
        </div>
      </section>

      <section className="grid grid-cols-2 gap-px overflow-hidden border-2 border-ink bg-line sm:grid-cols-3 lg:grid-cols-6">
        {[
          <Stat key="roi" label="ROI" value={c.bets_placed ? signedPct(c.roi) : "—"} tone={c.bets_placed ? (c.roi >= 0 ? "up" : "down") : "ink"} />,
          <Stat key="pnl" label="Net P&L" value={signedMoney(c.net_pnl)} tone={c.net_pnl >= 0 ? "up" : "down"} />,
          <Stat key="acc" label="Hit rate" value={c.accuracy.graded ? pct(c.accuracy.hit_rate) : "—"} sub={`${c.accuracy.graded} graded`} />,
          <Stat key="rec" label="Record" value={`${c.wins}-${c.losses}-${c.voids}`} sub="W-L-V" />,
          <Stat key="bets" label="Bets / Pass" value={`${c.bets_placed} / ${c.passes}`} />,
          <Stat key="avg" label="Avg stake" value={c.bets_placed ? money(c.avg_stake) : "—"} sub={c.bets_placed ? pct(c.avg_stake_pct) + " of start" : undefined} />,
          <Stat key="pts" label="Acc. points" value={c.accuracy.points} sub={`${c.accuracy.exact} exact`} />,
          <Stat key="adv" label="Advancers" value={c.accuracy.advance} sub="KO calls" />,
          <Stat key="staked" label="Total staked" value={money(c.total_staked)} />,
          <Stat key="tok" label="Tokens" value={c.telemetry.tokens.toLocaleString("en-US")} />,
          <Stat key="cost" label="Compute cost" value={`$${c.telemetry.cost_usd.toFixed(2)}`} />,
          <Stat key="calls" label="Model calls" value={c.telemetry.calls} />,
        ].map((node, i) => (
          <div key={i} className="bg-surface p-4">
            {node}
          </div>
        ))}
      </section>

      {/* bankroll history */}
      <section>
        <h2 className="mb-4 inline-flex items-center gap-2 font-display text-xl font-bold text-ink">
          <ChartLineUp size={20} weight="bold" className="text-volt" /> Bankroll over time
        </h2>
        {c.bankroll_history.length > 0 ? (
          <Card>
            <div className="p-5">
              <BankrollChart history={c.bankroll_history} starting={c.starting_bankroll} color={kit} />
            </div>
          </Card>
        ) : (
          <Empty icon={ChartLineUp} title="No movement yet">
            The bankroll line starts drawing once {c.model} settles its first bet. Check
            back after kickoff.
          </Empty>
        )}
      </section>

      {/* bet log */}
      <section>
        <h2 className="mb-4 inline-flex items-center gap-2 font-display text-xl font-bold text-ink">
          <ListChecks size={20} weight="bold" className="text-volt" /> Bet log
        </h2>
        {c.log.length > 0 ? (
          <div className="overflow-x-auto border border-line-strong bg-surface shadow-[6px_6px_0_rgba(22,29,24,.12)]">
            <table className="w-full min-w-[680px] text-sm">
              <thead>
                <tr className="mono border-b border-line text-[10px] uppercase tracking-[0.14em] text-faint">
                  <th className="px-4 py-3 text-left font-medium">Match</th>
                  <th className="px-4 py-3 text-left font-medium">Pick</th>
                  <th className="px-4 py-3 text-right font-medium">Stake</th>
                  <th className="px-4 py-3 text-right font-medium">Odds</th>
                  <th className="px-4 py-3 text-right font-medium">Result</th>
                  <th className="px-4 py-3 text-right font-medium">P&amp;L</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {c.log.map((e) => (
                  <tr key={e.fixture_id} className="hover:bg-surface-2">
                    <td className="px-4 py-3">
                      <Link href={`/fixtures/${e.fixture_id}`} className="flex items-center gap-2 text-ink hover:text-volt">
                        {e.fixture && (
                          <>
            <Flag iso={e.fixture.home.iso} name={e.fixture.home.name} code={e.fixture.home.code} h={16} />
                            <span className="text-xs text-muted">vs</span>
                            <Flag iso={e.fixture.away.iso} name={e.fixture.away.name} code={e.fixture.away.code} h={16} />
                          </>
                        )}
                      </Link>
                    </td>
                    <td className="mono px-4 py-3 text-left text-xs uppercase text-muted">{e.pick ?? "pass"}</td>
                    <td className="mono px-4 py-3 text-right tabular-nums text-muted">{e.stake ? money(e.stake) : "—"}</td>
                    <td className="mono px-4 py-3 text-right tabular-nums text-muted">{e.odds_at_bet?.toFixed(2) ?? "—"}</td>
                    <td className="mono px-4 py-3 text-right text-xs uppercase text-muted">{e.result ?? "—"}</td>
                    <td className={`mono px-4 py-3 text-right tabular-nums ${(e.pnl ?? 0) > 0 ? "text-up" : (e.pnl ?? 0) < 0 ? "text-down" : "text-faint"}`}>
                      {e.pnl != null ? signedMoney(e.pnl) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty icon={Coins} title="No bets placed yet">
            {c.model} has not staked a bet. Its first wager lands when the tournament
            begins and the opening briefings go out.
          </Empty>
        )}
      </section>
    </div>
  );
}

function DossierRow({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Lightning;
  label: string;
  value: string;
}) {
  return (
    <div className="grid grid-cols-[34px_110px_1fr] items-center gap-3 bg-bg px-3 py-3">
      <Icon size={18} weight="bold" className="text-volt" />
      <span className="mono text-[9px] uppercase tracking-[0.12em] text-faint">{label}</span>
      <span className="text-sm font-semibold text-ink">{value}</span>
    </div>
  );
}
