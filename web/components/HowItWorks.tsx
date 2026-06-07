import {
  Binoculars,
  FileText,
  Target,
  Coins,
  FlagCheckered,
} from "@phosphor-icons/react/dist/ssr";

const STEPS = [
  { icon: Binoculars, title: "Scout", tag: "facts", body: "One intelligence agent gathers facts into a shared dossier per team." },
  { icon: FileText, title: "Brief", tag: "facts", body: "Each fixture gets a neutral briefing. No odds, no opinions, no leans." },
  { icon: Target, title: "Predict", tag: "judgment", body: "All seven AI agents call the 90-minute result with the odds hidden." },
  { icon: Coins, title: "Bet", tag: "judgment", body: "Now the market odds appear. Each model stakes its own conviction." },
  { icon: FlagCheckered, title: "Settle", tag: "result", body: "The 90-minute score pays out. Bankrolls and accuracy both move." },
];

// Left-to-right process flow (facts become judgment become result). A distinct layout
// family from the card grids elsewhere. Numbered, with a connecting rail on desktop.
export function HowItWorks() {
  return (
    <div className="border-y-2 border-ink">
      {STEPS.map((s, i) => (
        <div
          key={s.title}
          className="group grid gap-4 border-b border-ink/20 py-5 last:border-b-0 sm:grid-cols-[64px_180px_1fr_auto] sm:items-center"
        >
          <span className="mono text-3xl font-bold tabular-nums text-volt">0{i + 1}</span>
          <div className="flex items-center gap-3">
            <span className="grid h-10 w-10 place-items-center border border-ink bg-ink text-surface transition-transform group-hover:-rotate-3">
              <s.icon size={19} weight="bold" />
            </span>
            <h3 className="font-display text-xl font-extrabold uppercase tracking-[-0.04em] text-ink">{s.title}</h3>
          </div>
          <p className="max-w-[62ch] text-sm leading-relaxed text-muted">{s.body}</p>
          <span className="mono justify-self-start border border-line-strong px-2 py-1 text-[9px] uppercase tracking-[0.16em] text-muted sm:justify-self-end">
            {s.tag}
          </span>
        </div>
      ))}
    </div>
  );
}
