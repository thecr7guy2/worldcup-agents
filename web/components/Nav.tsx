"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  HouseLine,
  Trophy,
  SoccerBall,
  Flask,
  UsersThree,
} from "@phosphor-icons/react";

const LINKS = [
  { href: "/", label: "Arena", short: "01", icon: HouseLine },
  { href: "/roster", label: "Agents", short: "02", icon: UsersThree },
  { href: "/leaderboard", label: "Table", short: "03", icon: Trophy },
  { href: "/fixtures", label: "Matches", short: "04", icon: SoccerBall },
  { href: "/lab", label: "Compute", short: "05", icon: Flask },
];

export function Nav() {
  const path = usePathname();
  return (
    <header className="sticky top-0 z-50 border-b border-white/10 bg-ink text-surface">
      <nav className="mx-auto flex h-[72px] max-w-[1500px] items-stretch px-4 sm:px-6">
        <Link href="/" className="group flex shrink-0 items-center gap-3 border-r border-white/10 pr-5">
          <span className="registration grid h-10 w-10 place-items-center bg-volt font-display text-[11px] font-extrabold leading-none text-surface">
            WC
            <br />
            26
          </span>
          <span className="hidden flex-col leading-none md:flex">
            <span className="font-display text-base font-extrabold uppercase tracking-[-0.04em] text-surface">
              THE ARENA
            </span>
            <span className="mono mt-1 text-[9px] uppercase tracking-[0.2em] text-surface/45">
              AI World Cup showdown
            </span>
          </span>
        </Link>

        <div className="ml-auto flex items-stretch overflow-x-auto">
          {LINKS.map(({ href, label, short, icon: Icon }) => {
            const active = href === "/" ? path === "/" : path.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                aria-label={label}
                className={`group relative flex shrink-0 items-center gap-2 border-l border-white/10 px-3 text-sm font-medium transition-colors sm:px-4 ${
                  active
                    ? "bg-volt text-surface"
                    : "text-surface/60 hover:bg-white/5 hover:text-surface"
                }`}
              >
                <span className={`mono hidden text-[9px] sm:inline ${active ? "text-surface/65" : "text-surface/30"}`}>
                  {short}
                </span>
                <Icon size={16} weight={active ? "fill" : "regular"} className="sm:hidden" />
                <span className="hidden sm:inline">{label}</span>
              </Link>
            );
          })}
        </div>
      </nav>
    </header>
  );
}
