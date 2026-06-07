import type { Icon } from "@phosphor-icons/react";
import type { ReactNode } from "react";

// Composed empty state (taste-skill §4.5): says what is missing and when it fills in.
export function Empty({
  icon: IconCmp,
  title,
  children,
}: {
  icon: Icon;
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="registration flex flex-col items-center justify-center border border-line-strong bg-surface px-6 py-14 text-center">
      <span className="grid h-12 w-12 place-items-center bg-ink text-surface">
        <IconCmp size={24} weight="bold" />
      </span>
      <h3 className="mt-4 font-display text-xl font-extrabold uppercase tracking-[-0.04em] text-ink">{title}</h3>
      {children && <p className="mt-1.5 max-w-[42ch] text-sm text-muted">{children}</p>}
    </div>
  );
}
