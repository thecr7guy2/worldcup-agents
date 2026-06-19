import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, Target, MapPin, Brain, CaretDown, FileText } from "@phosphor-icons/react/dist/ssr";
import { getFixture } from "@/lib/api";
import type { BoardEntry, TeamSide } from "@/lib/api";
import { money, pct, signedMoney, stageLabel, kickoffParts, outcomeLabel } from "@/lib/format";
import { Flag } from "@/components/Flag";
import { Empty } from "@/components/Empty";
import { Reveal } from "@/components/Reveal";
import { MarketBar } from "@/components/MarketBar";
import { Disagreement } from "@/components/Disagreement";
import { Briefing } from "@/components/Briefing";

export default async function FixturePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  let fx;
  try {
    fx = await getFixture(id);
  } catch {
    notFound();
  }
  const f = fx!;
  const k = kickoffParts(f.kickoff);
  const finished = f.status === "finished" && f.result != null;
  const hasPredictions = f.board.some((b) => b.prediction != null);

  return (
    <div className="flex flex-col gap-10">
      <Link href="/fixtures" className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink">
        <ArrowLeft size={15} weight="bold" /> All fixtures
      </Link>

      {/* match header */}
      <section className="pitch-grid overflow-hidden border-2 border-ink bg-ink p-6 text-surface shadow-[8px_8px_0_var(--color-volt)] sm:p-8">
        <div className="mono mb-6 flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-center text-[12px] uppercase tracking-[0.16em] text-surface/45">
          <span className="text-volt">{stageLabel(f.stage)}{f.group ? ` · Group ${f.group}` : ""}</span>
          <span className="hidden sm:inline">·</span>
          <span>{k.day}, {k.time} UTC</span>
          {f.venue && (
            <>
              <span className="hidden sm:inline">·</span>
              <span className="inline-flex items-center gap-1"><MapPin size={12} /> {f.venue}</span>
            </>
          )}
        </div>

        <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-4 sm:gap-8">
          <TeamBig side={f.home} align="right" winner={f.result?.outcome === "home"} />
          <div className="text-center">
            {finished && f.result ? (
              <div className="mono text-4xl font-bold tabular-nums text-surface sm:text-5xl">
                {f.result.home_goals}<span className="px-1 text-surface/30">:</span>{f.result.away_goals}
              </div>
            ) : (
              <div className="mono text-2xl font-bold uppercase tracking-[0.2em] text-surface/30">vs</div>
            )}
            {finished && (f.result?.went_penalties || f.result?.went_extra_time) && (
              <div className="mono mt-1 text-[10px] uppercase tracking-wider text-faint">
                {f.result?.went_penalties ? "after penalties" : "after extra time"}
              </div>
            )}
          </div>
          <TeamBig side={f.away} align="left" winner={f.result?.outcome === "away"} />
        </div>

        {/* odds strip */}
        {f.odds && (
          <div className="mx-auto mt-7 grid max-w-md grid-cols-3 gap-2">
            <OddPill label={f.home.code ?? "Home"} value={f.odds.home} />
            <OddPill label="Draw" value={f.odds.draw} />
            <OddPill label={f.away.code ?? "Away"} value={f.odds.away} />
          </div>
        )}
      </section>

      {/* market read — implied probability from live odds (renders pre-kickoff) */}
      {f.odds && (
        <section className="border-2 border-ink bg-surface p-5 shadow-[6px_6px_0_rgba(22,29,24,.12)] sm:p-6">
          <MarketBar fx={f} />
          <p className="mono mt-3 text-[9px] uppercase tracking-[0.13em] text-faint">
            The market&apos;s read only. Models predict with these odds hidden — compare against
            the board below once predictions lock.
          </p>
        </section>
      )}

      {/* the briefing — the neutral, odds-free dossier every model reasoned from. Collapsed by
          default so it never crowds the page; native <details> keeps it server-rendered. */}
      {f.briefing && (
        <details className="group border-2 border-ink bg-surface shadow-[6px_6px_0_rgba(22,29,24,.12)] [&_summary::-webkit-details-marker]:hidden">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 p-5 sm:p-6">
            <span className="flex items-center gap-2.5">
              <FileText size={20} weight="bold" className="text-volt" />
              <span>
                <span className="block font-display text-lg font-bold text-ink">The briefing</span>
                <span className="mono block text-[10px] uppercase tracking-[0.14em] text-faint">
                  The exact facts every model saw · no odds, no lean
                </span>
              </span>
            </span>
            <span className="mono flex shrink-0 items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-muted group-hover:text-volt">
              <span className="hidden sm:inline group-open:hidden">Read</span>
              <span className="hidden sm:group-open:inline">Close</span>
              <CaretDown size={16} weight="bold" className="transition-transform group-open:rotate-180" />
            </span>
          </summary>
          <div className="border-t border-line px-5 pb-6 pt-4 sm:px-6">
            <Briefing content={f.briefing} />
          </div>
        </details>
      )}

      {/* the board */}
      <section>
        <h2 className="mb-1 flex items-center gap-2 font-display text-xl font-bold text-ink">
          <Target size={20} weight="bold" className="text-volt" /> The board
        </h2>
        <p className="mb-5 text-sm text-muted">
          Each model predicts with odds hidden, then bets once the market is revealed.
        </p>

        {hasPredictions ? (
          <>
            <Reveal>
              <div className="mb-6">
                <Disagreement entries={f.board} home={f.home} away={f.away} />
              </div>
            </Reveal>
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              {f.board.map((b, i) => (
                <Reveal key={b.model} delay={i * 0.03}>
                  <BoardCard entry={b} home={f.home} away={f.away} />
                </Reveal>
              ))}
            </div>
          </>
        ) : (
          <>
            <Empty icon={Target} title={f.briefed ? "Predictions incoming" : "Briefing not yet built"}>
              {f.briefed
                ? "The dossier is ready. Model predictions appear here once they lock in, a few hours before kickoff."
                : "This fixture's neutral briefing is assembled within 24 hours of kickoff. Predictions follow."}
            </Empty>
            <div className="mt-6">
              <div className="mono mb-3 text-[11px] uppercase tracking-[0.16em] text-faint">
                Contenders on the slate
              </div>
              <div className="flex flex-wrap gap-2">
                {f.board.map((b) => (
                  <Link
                    key={b.model}
                    href={`/agents/${encodeURIComponent(b.model)}`}
                    className="flex items-center gap-2 rounded-full border border-line bg-surface px-3 py-1.5 text-sm text-muted transition-colors hover:border-line-strong hover:text-ink"
                  >
                    <span className="grid h-5 w-5 place-items-center rounded-[5px] font-display text-[11px] font-bold text-bg" style={{ background: b.meta.color }}>
                      {b.meta.sigil}
                    </span>
                    {b.model}
                  </Link>
                ))}
              </div>
            </div>
          </>
        )}
      </section>
    </div>
  );
}

function TeamBig({ side, align, winner }: { side: TeamSide; align: "left" | "right"; winner?: boolean }) {
  return (
    <div className={`flex flex-col items-center gap-3 ${align === "right" ? "sm:items-end" : "sm:items-start"}`}>
      <Flag iso={side.iso} name={side.name} code={side.code} h={46} className="shadow-lg" />
      <div className={`text-center ${align === "right" ? "sm:text-right" : "sm:text-left"}`}>
        <div className={`font-display text-lg font-extrabold uppercase leading-tight tracking-[-0.04em] sm:text-2xl ${winner ? "text-volt" : "text-surface"}`}>
          {side.name}
        </div>
        {side.group && (
          <div className="mono mt-0.5 text-[11px] uppercase tracking-wider text-faint">Group {side.group}</div>
        )}
      </div>
    </div>
  );
}

function OddPill({ label, value }: { label: string; value: number }) {
  return (
    <div className="border border-white/20 bg-surface px-3 py-2.5 text-center text-ink">
      <div className="mono text-[10px] uppercase tracking-wider text-faint">{label}</div>
      <div className="mono mt-0.5 text-lg font-bold tabular-nums text-ink">{value.toFixed(2)}</div>
    </div>
  );
}

function BoardCard({ entry, home, away }: { entry: BoardEntry; home: TeamSide; away: TeamSide }) {
  const p = entry.prediction;
  const b = entry.bet;
  const s = entry.settlement;
  const kit = entry.meta.color;

  return (
    <div className="border border-line-strong bg-surface p-4 shadow-[5px_5px_0_rgba(22,29,24,.12)]">
      <div className="flex items-center justify-between">
        <Link href={`/agents/${encodeURIComponent(entry.model)}`} className="flex items-center gap-2.5 hover:text-volt">
          <span className="registration grid h-8 w-8 place-items-center font-display text-sm font-bold text-surface" style={{ background: kit }}>
            {entry.meta.sigil}
          </span>
          <span>
            <span className="block font-display font-bold text-ink">{entry.model}</span>
            <span className="mono block text-[9px] uppercase text-faint">{entry.meta.vendor}</span>
          </span>
        </Link>
        {p && (
          <span className="mono text-[11px] uppercase tracking-wider text-faint">
            {pct(p.confidence, 0)} sure
          </span>
        )}
      </div>

      {p && (
        <div className="mt-3 space-y-2 text-sm">
          <Row label="Predicts">
            <span className="font-medium text-ink">
              {outcomeLabel(p.winner, home.name, away.name)}
              {p.winner !== "draw" && <span className="font-normal text-muted"> to win</span>}
            </span>
            {p.pred_home_goals != null && p.pred_away_goals != null && (
              <span className="mono ml-2 text-[11px] text-faint">
                {home.code ?? "H"} {p.pred_home_goals}–{p.pred_away_goals} {away.code ?? "A"}
              </span>
            )}
          </Row>
          {p.p_home != null && p.p_draw != null && p.p_away != null && (
            <Row label="Win prob">
              <span className="mono text-[11px] text-muted">
                {home.code ?? "H"} {pct(p.p_home, 0)} · D {pct(p.p_draw, 0)} · {away.code ?? "A"} {pct(p.p_away, 0)}
              </span>
            </Row>
          )}
          {b && b.pick && b.stake > 0 ? (
            <Row label="Bets">
              <span className="font-medium text-ink">{outcomeLabel(b.pick, home.name, away.name)}</span>
              <span className="mono ml-2 text-muted">
                {money(b.stake)}{b.odds_at_bet ? ` @ ${b.odds_at_bet.toFixed(2)}` : ""}
              </span>
            </Row>
          ) : b ? (
            <Row label="Bets"><span className="text-faint">Passed</span></Row>
          ) : null}
          {s && (
            <Row label="Result">
              <span className={`mono uppercase ${s.result === "win" ? "text-up" : s.result === "loss" ? "text-down" : "text-faint"}`}>
                {s.result}
              </span>
              {s.result !== "pass" && (
                <span className={`mono ml-2 ${s.pnl >= 0 ? "text-up" : "text-down"}`}>{signedMoney(s.pnl)}</span>
              )}
            </Row>
          )}
          {entry.decision_receipt && (
            <DecisionReceipt receipt={entry.decision_receipt} home={home} away={away} />
          )}
          {(p.reasoning || (b && b.reasoning)) && (
            <Rationale prediction={p.reasoning} bet={b?.reasoning} />
          )}
        </div>
      )}
    </div>
  );
}

function DecisionReceipt({
  receipt,
  home,
  away,
}: {
  receipt: NonNullable<BoardEntry["decision_receipt"]>;
  home: TeamSide;
  away: TeamSide;
}) {
  const chosen =
    receipt.chosen_stake_pct == null
      ? receipt.outcome === "pass"
        ? "pass"
        : "pending"
      : receipt.chosen_stake_pct === 0
        ? "pass"
        : `${receipt.chosen_stake_pct.toFixed(0)}%`;
  const eligible = receipt.eligible.length
    ? receipt.eligible.map((o) => shortOutcome(o, home, away)).join(", ")
    : "none";

  return (
    <div className="mt-3 border border-line bg-bg p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="mono text-[9px] uppercase tracking-[0.14em] text-faint">Decision receipt</div>
          <div className="mt-1 font-display text-base font-extrabold uppercase leading-none text-ink">
            {receipt.outcome === "pass"
              ? "Passed"
              : receipt.outcome
                ? `${chosen} on ${shortOutcome(receipt.outcome, home, away)}`
                : "Awaiting bet"}
          </div>
        </div>
        <div className="mono text-right text-[10px] uppercase tracking-[0.12em] text-faint">
          target {receipt.matchday_target_pct.toFixed(0)}% / penalty {receipt.shortfall_penalty_pct.toFixed(1)}%
        </div>
      </div>

      <div className="mt-3 grid gap-px bg-line text-xs sm:grid-cols-3">
        <ReceiptMetric
          label="Blind forecast"
          value={`${home.code ?? "H"} ${pct(receipt.probabilities.home, 0)} / D ${pct(receipt.probabilities.draw, 0)} / ${away.code ?? "A"} ${pct(receipt.probabilities.away, 0)}`}
        />
        <ReceiptMetric
          label="Market implied"
          value={
            receipt.market_implied
              ? `${home.code ?? "H"} ${pct(receipt.market_implied.home, 0)} / D ${pct(receipt.market_implied.draw, 0)} / ${away.code ?? "A"} ${pct(receipt.market_implied.away, 0)}`
              : "no odds"
          }
        />
        <ReceiptMetric label="Allowed bets" value={eligible} />
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {receipt.available_tiers.map((tier) => (
          <span
            key={tier}
            className={`mono border px-2 py-1 text-[10px] font-bold uppercase ${
              receipt.chosen_stake_pct === tier
                ? "border-ink bg-ink text-surface"
                : "border-line bg-surface text-muted"
            }`}
          >
            {tier.toFixed(0)}%
          </span>
        ))}
      </div>

      {receipt.drivers.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {receipt.drivers.slice(0, 3).map((driver) => (
            <li key={driver} className="flex gap-2 text-[12px] leading-snug text-muted">
              <span className="mt-[0.35rem] h-1.5 w-1.5 shrink-0 bg-volt" />
              <span>{driver}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ReceiptMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-surface p-2.5">
      <div className="mono text-[8px] uppercase tracking-[0.12em] text-faint">{label}</div>
      <div className="mt-1 text-[12px] font-semibold leading-snug text-ink">{value}</div>
    </div>
  );
}

function shortOutcome(outcome: string, home: TeamSide, away: TeamSide) {
  if (outcome === "home") return home.code ?? home.name;
  if (outcome === "away") return away.code ?? away.name;
  if (outcome === "draw") return "Draw";
  return "Pass";
}

// Expandable "why this call" disclosure. Native <details> so it works with no
// client JS. Splits the model's own words into the two judgment steps — the
// prediction it made blind, then the bet it sized once the odds were revealed.
function Rationale({ prediction, bet }: { prediction: string; bet?: string | null }) {
  return (
    <details className="group mt-3 border-t border-line pt-3 [&_summary::-webkit-details-marker]:hidden">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 text-[11px] font-bold uppercase tracking-wider text-ink hover:text-volt">
        <span className="inline-flex items-center gap-1.5">
          <Brain size={14} weight="bold" className="text-volt" /> Why this call
        </span>
        <CaretDown size={14} weight="bold" className="transition-transform group-open:rotate-180" />
      </summary>
      <div className="mt-3 space-y-3">
        {prediction && (
          <div>
            <div className="mono mb-1 text-[9px] uppercase tracking-[0.14em] text-faint">
              Prediction · odds hidden
            </div>
            <p className="text-[13px] leading-relaxed text-muted">{prediction}</p>
          </div>
        )}
        {bet && (
          <div className="border-t border-dashed border-line pt-3">
            <div className="mono mb-1 text-[9px] uppercase tracking-[0.14em] text-faint">
              Bet · odds revealed
            </div>
            <p className="text-[13px] leading-relaxed text-muted">{bet}</p>
          </div>
        )}
      </div>
    </details>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline gap-2">
      <span className="mono w-16 shrink-0 text-[10px] uppercase tracking-wider text-faint">{label}</span>
      <span className="flex items-baseline">{children}</span>
    </div>
  );
}
