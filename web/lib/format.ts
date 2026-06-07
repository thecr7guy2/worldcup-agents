// Display formatters. All money/number output uses tabular figures (see .mono).

export function money(n: number): string {
  const abs = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(1)}k`;
  return `${sign}$${abs.toFixed(0)}`;
}

export function moneyFull(n: number): string {
  return `$${Math.round(n).toLocaleString("en-US")}`;
}

export function signedMoney(n: number): string {
  if (n === 0) return "$0";
  return `${n > 0 ? "+" : "-"}${money(Math.abs(n))}`;
}

export function compact(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(2)}B`;
  if (abs >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return `${n}`;
}

export function pct(n: number, digits = 1): string {
  return `${(n * 100).toFixed(digits)}%`;
}

export function signedPct(n: number, digits = 1): string {
  return `${n > 0 ? "+" : ""}${(n * 100).toFixed(digits)}%`;
}

const STAGE_LABELS: Record<string, string> = {
  group: "Group Stage",
  round_of_32: "Round of 32",
  round_of_16: "Round of 16",
  quarter_final: "Quarter-final",
  semi_final: "Semi-final",
  third_place: "Third Place",
  final: "Final",
};

export function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] ?? stage;
}

export function stageShort(stage: string): string {
  return (
    {
      group: "GROUP",
      round_of_32: "R32",
      round_of_16: "R16",
      quarter_final: "QF",
      semi_final: "SF",
      third_place: "3RD",
      final: "FINAL",
    }[stage] ?? stage.toUpperCase()
  );
}

export function flagUrl(iso: string | null, w = 80): string | null {
  // flagcdn serves SVG (and sized PNG); supports gb-eng / gb-sct subdivisions.
  return iso ? `https://flagcdn.com/w${w}/${iso}.png` : null;
}

export function flagSvg(iso: string | null): string | null {
  return iso ? `https://flagcdn.com/${iso}.svg` : null;
}

export function kickoffParts(iso: string): { day: string; time: string; weekday: string } {
  const d = new Date(iso);
  return {
    weekday: d.toLocaleDateString("en-US", { weekday: "short", timeZone: "UTC" }),
    day: d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" }),
    time: d.toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZone: "UTC",
    }),
  };
}

export function outcomeLabel(o: string | null, home: string, away: string): string {
  if (o === "home") return home;
  if (o === "away") return away;
  if (o === "draw") return "Draw";
  return "TBD";
}

export interface ImpliedProbs {
  home: number;
  draw: number;
  away: number;
  overround: number;
}

// Decimal odds -> implied outcome probabilities. Raw 1/odds sum to >1 (the
// bookmaker's margin / "overround"); we normalize so the three add to 100% and
// surface the margin separately for the curious.
export function impliedProbs(odds: {
  home: number;
  draw: number;
  away: number;
}): ImpliedProbs {
  const rh = 1 / odds.home;
  const rd = 1 / odds.draw;
  const ra = 1 / odds.away;
  const sum = rh + rd + ra;
  return {
    home: rh / sum,
    draw: rd / sum,
    away: ra / sum,
    overround: sum - 1,
  };
}
