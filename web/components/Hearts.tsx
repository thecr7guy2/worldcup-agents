import { Heart, HeartBreak, Skull } from "@phosphor-icons/react/dist/ssr";

// Lives, video-game style. Total lives = the original run + allowed rebuys (max_lives).
// Spent lives show as broken hearts; a busted (inactive) competitor shows a skull.
export function Hearts({
  livesUsed,
  maxLives,
  active,
  size = 16,
}: {
  livesUsed: number;
  maxLives: number;
  active: boolean;
  size?: number;
}) {
  const total = maxLives + 1;
  if (!active) {
    return (
      <span className="inline-flex items-center gap-1 text-down" title="Eliminated">
        <Skull size={size} weight="fill" />
        <span className="mono text-[11px] uppercase tracking-wider">Out</span>
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-0.5" title={`${total - livesUsed} of ${total} lives`}>
      {Array.from({ length: total }).map((_, i) =>
        i < total - livesUsed ? (
          <Heart key={i} size={size} weight="fill" className="text-down" />
        ) : (
          <HeartBreak key={i} size={size} weight="regular" className="text-faint" />
        ),
      )}
    </span>
  );
}
