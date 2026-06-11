import { Fragment, type ReactNode } from "react";

// Renderer for the match-briefing markdown — a deliberately small, in-repo renderer rather
// than a markdown dependency, because the intelligence agent emits a tight, controlled subset:
// `#`/`##` headings, `-` bullets, paragraphs, `**bold**`, inline `[text](url)` citation links,
// and `---` rules. (Verified against live briefings: no tables, italics, nested or numbered
// lists, code, or blockquotes.) Server component — keeps the surrounding <details> JS-free.

// Inline pass: split a line into bold spans and links, leaving everything else as plain text.
const INLINE = /\*\*(.+?)\*\*|\[([^\]]+)\]\(([^)]+)\)/g;

function renderInline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  INLINE.lastIndex = 0;
  while ((m = INLINE.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    if (m[1] !== undefined) {
      // **bold**
      out.push(
        <strong key={i++} className="font-semibold text-ink">
          {m[1]}
        </strong>,
      );
    } else {
      // [label](url) — rendered as a subtle citation link
      const label = m[2];
      const href = m[3];
      const safe = /^https?:\/\//i.test(href);
      out.push(
        safe ? (
          <a
            key={i++}
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="mono text-[11px] text-faint underline decoration-line underline-offset-2 transition-colors hover:text-volt"
          >
            {label}
          </a>
        ) : (
          <Fragment key={i++}>{label}</Fragment>
        ),
      );
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function Briefing({ content }: { content: string }) {
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let bullets: string[] = [];
  let key = 0;

  const flushBullets = () => {
    if (bullets.length === 0) return;
    const items = bullets;
    bullets = [];
    blocks.push(
      <ul key={key++} className="my-2 space-y-1.5 pl-1">
        {items.map((b, j) => (
          <li key={j} className="flex gap-2 text-[13px] leading-relaxed text-muted">
            <span aria-hidden className="mt-[7px] h-1 w-1 shrink-0 bg-volt" />
            <span>{renderInline(b)}</span>
          </li>
        ))}
      </ul>,
    );
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    const s = line.trim();

    if (s === "") {
      flushBullets();
      continue;
    }
    if (s === "---" || s === "***" || s === "___") {
      flushBullets();
      blocks.push(<hr key={key++} className="my-5 border-t border-line" />);
      continue;
    }
    if (s.startsWith("## ")) {
      flushBullets();
      blocks.push(
        <h3
          key={key++}
          className="mt-6 mb-2 font-display text-base font-bold uppercase tracking-[-0.02em] text-ink first:mt-0"
        >
          {renderInline(s.slice(3))}
        </h3>,
      );
      continue;
    }
    if (s.startsWith("# ")) {
      flushBullets();
      blocks.push(
        <div
          key={key++}
          className="mono mb-3 text-[11px] uppercase tracking-[0.16em] text-faint first:mt-0"
        >
          {renderInline(s.slice(2))}
        </div>,
      );
      continue;
    }
    const bullet = s.match(/^[-*–•]\s+(.*)$/);
    if (bullet) {
      bullets.push(bullet[1]);
      continue;
    }
    // paragraph
    flushBullets();
    blocks.push(
      <p key={key++} className="my-2 text-[13px] leading-relaxed text-muted">
        {renderInline(s)}
      </p>,
    );
  }
  flushBullets();

  return <div className="briefing-prose">{blocks}</div>;
}
