import {
  Books,
  ChartLineUp,
  ClockCountdown,
  CursorText,
  MusicNotes,
  Plant,
  Strategy,
} from "@phosphor-icons/react/dist/ssr";
import type { AgentMeta } from "@/lib/api";

const ICONS = {
  rhythm: MusicNotes,
  strategy: Strategy,
  clock: ClockCountdown,
  plant: Plant,
  books: Books,
  cursor: CursorText,
  chart: ChartLineUp,
};

export function PersonaEmblem({
  meta,
  size = 72,
  className = "",
}: {
  meta: AgentMeta;
  size?: number;
  className?: string;
}) {
  const Icon = ICONS[meta.emblem] ?? Strategy;
  return (
    <div
      className={`registration relative grid place-items-center border-2 border-current ${className}`}
      aria-hidden
    >
      <Icon size={size} weight="duotone" />
      <span className="mono absolute -bottom-2 -right-2 bg-ink px-1.5 py-0.5 text-[9px] font-bold text-surface">
        {meta.sigil}
      </span>
    </div>
  );
}
