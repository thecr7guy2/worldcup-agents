import { flagSvg } from "@/lib/format";

// Real flag SVG (flagcdn) — never an emoji or hand-drawn shape (taste-skill §4.8/§9).
// Unresolved bracket slots get a neutral monogram placeholder instead.
export function Flag({
  iso,
  name,
  code,
  h = 22,
  className = "",
}: {
  iso: string | null;
  name: string;
  code?: string | null;
  h?: number;
  className?: string;
}) {
  const w = Math.round(h * 1.4);
  if (!iso) {
    return (
      <span
        aria-label={name}
        className={`inline-flex items-center justify-center rounded-[3px] bg-elevated text-faint font-mono ${className}`}
        style={{ width: w, height: h, fontSize: h * 0.42 }}
      >
        {code ?? name.slice(0, 3)}
      </span>
    );
  }
  return (
    <img
      src={flagSvg(iso)!}
      alt={`${name} flag`}
      width={w}
      height={h}
      loading="lazy"
      className={`rounded-[3px] object-cover ring-1 ring-line-strong ${className}`}
      style={{ width: w, height: h }}
    />
  );
}
