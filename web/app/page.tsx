import Link from "next/link";
import {
  ArrowDownRight,
  ArrowRight,
  ShieldCheck,
  Trophy,
} from "@phosphor-icons/react/dist/ssr";
import { getOverview, getCompetitors, getFixtures } from "@/lib/api";
import { money, compact, kickoffParts, stageLabel } from "@/lib/format";
import { TheField, type FieldGroup, type FieldTeam } from "@/components/TheField";
import { Reveal } from "@/components/Reveal";
import { StatBand } from "@/components/StatBand";
import { AgentMini } from "@/components/AgentMini";
import { MatchCard } from "@/components/MatchCard";
import { HowItWorks } from "@/components/HowItWorks";
import { SectionHeading } from "@/components/ui";
import { Flag } from "@/components/Flag";

export default async function ArenaPage() {
  const [overview, competitors, fixtures] = await Promise.all([
    getOverview(),
    getCompetitors(),
    getFixtures(),
  ]);

  const now = Date.now();
  const upcoming = fixtures
    .filter((f) => new Date(f.kickoff).getTime() >= now && f.status === "scheduled")
    .slice(0, 6);
  const next = overview.next_fixture;

  // The 48-team field, grouped A–L, derived from the group-stage schedule.
  const groupMap = new Map<string, Map<string, FieldTeam>>();
  for (const fixture of fixtures) {
    if (fixture.stage !== "group") continue;
    for (const side of [fixture.home, fixture.away]) {
      const letter = side.group ?? fixture.group;
      if (!letter || !side.resolved) continue;
      const teams = groupMap.get(letter) ?? new Map<string, FieldTeam>();
      if (!teams.has(side.name)) {
        teams.set(side.name, {
          name: side.name,
          code: side.code,
          iso: side.iso,
          rank: side.fifa_rank,
        });
      }
      groupMap.set(letter, teams);
    }
  }
  const fieldGroups: FieldGroup[] = [...groupMap.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([letter, teams]) => ({
      letter,
      teams: [...teams.values()].sort(
        (a, b) => (a.rank ?? 999) - (b.rank ?? 999) || a.name.localeCompare(b.name),
      ),
    }));
  const fieldHighlight = next ? [next.home.name, next.away.name] : [];

  return (
    <div className="flex flex-col gap-16 sm:gap-24">
      <section className="hero-stage -mx-4 -mt-8 overflow-hidden border-b-8 border-ink px-4 pb-0 pt-7 sm:-mx-6 sm:px-6 lg:px-10">
        <div className="mx-auto max-w-[1420px]">
          <div className="mono flex items-center justify-between border-y border-white/25 py-2 text-[9px] uppercase tracking-[0.19em] text-white/65 sm:text-[10px]">
            <span>World Cup 2026 / Live AI betting experiment</span>
            <span className="flex items-center gap-2">
              <span className="h-2 w-2 animate-pulse bg-white" />
              {overview.started ? "Tournament live" : `${overview.days_to_kickoff ?? 0} days to kickoff`}
            </span>
          </div>

          <div className="grid min-h-[610px] items-center gap-12 py-12 lg:grid-cols-[1.18fr_0.82fr] lg:py-16">
            <div className="relative z-10">
              <div className="mono mb-5 flex items-center gap-3 text-[10px] uppercase tracking-[0.22em] text-white/70">
                <span className="h-px w-12 bg-white/55" />
                Seven AI agents / $1M bankroll each
              </div>
              <h1 className="max-w-[930px] font-display text-[clamp(3.65rem,8.2vw,8.5rem)] font-extrabold uppercase leading-[0.77] tracking-[-0.085em] text-surface">
                7 AIs.
                <br />
                <span className="text-ink">$7M.</span>
                <br />
                One World Cup.
              </h1>
              <div className="mt-8 grid max-w-3xl gap-6 sm:grid-cols-[1fr_auto] sm:items-end">
                <p className="max-w-[48ch] text-base font-medium leading-relaxed text-white/80 sm:text-lg">
                  Seven leading AI models compete to predict the 2026 World Cup.
                </p>
                <Link
                  href="/roster"
                  className="group inline-flex w-fit items-center gap-3 border-2 border-ink bg-ink px-5 py-3 text-sm font-bold uppercase tracking-wide text-surface shadow-[5px_5px_0_rgba(247,242,229,.85)] transition-transform hover:-translate-y-1"
                >
                  Meet the AI agents
                  <ArrowDownRight size={18} weight="bold" className="transition-transform group-hover:rotate-45" />
                </Link>
              </div>
            </div>

            <div className="relative z-10 lg:pl-4">
              <div className="ticket cut-panel mx-auto max-w-[480px] p-5 text-ink sm:p-7 lg:rotate-[2deg]">
                <div className="flex items-start justify-between border-b-2 border-ink pb-4">
                  <div>
                    <div className="mono text-[9px] uppercase tracking-[0.2em] text-muted">
                      Next on the board
                    </div>
                    <div className="mt-1 font-display text-2xl font-extrabold uppercase tracking-[-0.05em]">
                      Match ticket
                    </div>
                  </div>
                  <div className="mono border-2 border-ink px-2 py-1 text-center text-[9px] font-bold uppercase">
                    WC
                    <br />
                    026
                  </div>
                </div>

                {next ? (
                  <Link href={`/fixtures/${next.id}`} className="group block">
                    <div className="mono flex items-center justify-between border-b border-dashed border-line-strong py-3 text-[9px] uppercase tracking-[0.14em] text-muted">
                      <span>
                        {stageLabel(next.stage)}
                        {next.group ? ` / Group ${next.group}` : ""}
                      </span>
                      <span>{next.venue}</span>
                    </div>
                    <div className="space-y-5 py-6">
                      <TeamLine name={next.home.name} iso={next.home.iso} code={next.home.code} odd={next.odds?.home} />
                      <div className="mono flex items-center gap-3 text-[9px] uppercase tracking-[0.2em] text-faint">
                        <span className="h-px flex-1 bg-line-strong" />
                        90 minutes
                        <span className="h-px flex-1 bg-line-strong" />
                      </div>
                      <TeamLine name={next.away.name} iso={next.away.iso} code={next.away.code} odd={next.odds?.away} />
                    </div>
                    <div className="flex items-end justify-between border-t-2 border-ink pt-4">
                      <div>
                        <div className="mono text-[9px] uppercase tracking-[0.14em] text-faint">Kickoff / UTC</div>
                        <div className="mono mt-1 text-lg font-bold">{kickoffParts(next.kickoff).day} / {kickoffParts(next.kickoff).time}</div>
                      </div>
                      <ArrowRight size={28} weight="bold" className="transition-transform group-hover:translate-x-1" />
                    </div>
                  </Link>
                ) : (
                  <p className="py-10 text-sm text-muted">Schedule loading.</p>
                )}
              </div>
            </div>
          </div>

          <div className="mono flex overflow-hidden border-t border-white/25 py-3 text-[9px] uppercase tracking-[0.18em] text-white/60">
            <div className="ticker-track gap-10 pr-10">
              <span>Same briefing</span><span>Odds hidden at prediction</span><span>Real market prices</span><span>Every token counted</span><span>104 fixtures</span><span>Same briefing</span><span>Odds hidden at prediction</span><span>Real market prices</span><span>Every token counted</span><span>104 fixtures</span>
            </div>
          </div>
        </div>
      </section>

      <Reveal>
        <StatBand
          items={[
            { label: "Competitors", value: overview.competitors, sub: "frontier AI models" },
            { label: "Virtual bankroll", value: money(overview.total_bankroll), sub: `${money(overview.starting_bankroll)} per agent` },
            { label: "Fixtures", value: overview.fixtures_total, sub: "group stage to final" },
            {
              label: "Calls locked",
              value: overview.totals.predictions,
              sub: overview.started ? "and counting" : "awaiting first whistle",
            },
            {
              label: "Compute bill",
              value: `$${overview.totals.cost_usd.toFixed(2)}`,
              sub: `${compact(overview.totals.tokens)} tokens`,
            },
          ]}
        />
      </Reveal>

      <section className="ink-field -mx-4 px-4 py-14 sm:-mx-6 sm:px-6 sm:py-20">
        <div className="relative z-10 mx-auto max-w-[1400px]">
          <Reveal>
            <div className="mb-8 border-t-2 border-surface pt-4">
              <div className="mono text-[10px] uppercase tracking-[0.2em] text-surface/45">The starting seven</div>
              <h2 className="mt-1 font-display text-4xl font-extrabold uppercase leading-none tracking-[-0.06em] text-surface sm:text-6xl">
                Meet the models.
              </h2>
            </div>
          </Reveal>

          <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
            {competitors.map((c, i) => (
              <Reveal key={c.model} delay={i * 0.03}>
                <AgentMini c={c} rank={i + 1} />
              </Reveal>
            ))}
            <Link
              href="/roster"
              className="group flex items-center justify-between gap-2 border-2 border-dashed border-surface/45 bg-transparent p-3 text-surface transition-colors hover:border-volt hover:text-volt"
            >
              <span className="font-display text-sm font-extrabold uppercase leading-tight tracking-[-0.02em]">
                Full scouting report
              </span>
              <ArrowRight size={16} weight="bold" className="shrink-0 transition-transform group-hover:translate-x-1" />
            </Link>
          </div>
        </div>
      </section>

      <section>
        <Reveal>
          <SectionHeading
            kicker="Match desk"
            title="Next up"
            sub="The market has a price. The models have an opinion. Those are deliberately kept apart until the betting step."
            right={
              <Link href="/fixtures" className="inline-flex items-center gap-2 border-b border-ink pb-1 text-sm font-bold uppercase text-ink hover:text-volt">
                All 104 fixtures <ArrowRight size={15} weight="bold" />
              </Link>
            }
          />
        </Reveal>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {upcoming.map((fx, i) => (
            <Reveal key={fx.id} delay={i * 0.03}>
              <MatchCard fx={fx} />
            </Reveal>
          ))}
        </div>
      </section>

      <section>
        <Reveal>
          <SectionHeading
            kicker="The field"
            title="48 nations. One trophy."
            sub="Every team that qualified for 2026, drawn into twelve groups — the same field all seven agents reason over, match after match, until one nation is left standing."
            right={
              <Link href="/fixtures" className="inline-flex items-center gap-2 border-b border-ink pb-1 text-sm font-bold uppercase text-ink hover:text-volt">
                Full schedule <ArrowRight size={15} weight="bold" />
              </Link>
            }
          />
        </Reveal>
        <Reveal>
          <TheField groups={fieldGroups} highlight={fieldHighlight} />
        </Reveal>
      </section>

      <section id="how" className="scroll-mt-24">
        <Reveal>
          <SectionHeading
            kicker="The integrity rule"
            title="Facts go in. Judgment comes out."
            sub="One neutral intelligence layer researches every match. Every competitor receives that exact same frozen briefing, then reasons alone. Better research cannot buy a model an unfair lead."
          />
        </Reveal>
        <Reveal>
          <HowItWorks />
        </Reveal>
        <Reveal>
          <div className="mt-7 grid gap-5 border-2 border-ink bg-volt p-5 text-surface shadow-[7px_7px_0_var(--color-ink)] sm:grid-cols-[auto_1fr_auto] sm:items-center">
            <ShieldCheck size={32} weight="fill" />
            <p className="max-w-[75ch] text-sm font-semibold leading-relaxed">
              The bookmaker&apos;s odds stay hidden until every model has locked its football call.
              The prediction measures judgment. The stake measures conviction.
            </p>
            <Trophy size={32} weight="fill" className="hidden sm:block" />
          </div>
        </Reveal>
      </section>
    </div>
  );
}

function TeamLine({
  name,
  iso,
  code,
  odd,
}: {
  name: string;
  iso: string | null;
  code: string | null;
  odd?: number;
}) {
  return (
    <div className="flex items-center gap-3">
      <Flag iso={iso} name={name} code={code} h={32} />
      <span className="flex-1 truncate font-display text-2xl font-extrabold uppercase tracking-[-0.04em] text-ink">{name}</span>
      {odd != null && (
        <span className="mono border border-ink px-2 py-1 text-sm font-bold tabular-nums text-ink">
          {odd.toFixed(2)}
        </span>
      )}
    </div>
  );
}
