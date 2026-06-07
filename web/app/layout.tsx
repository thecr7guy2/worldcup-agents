import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { Bricolage_Grotesque } from "next/font/google";
import Link from "next/link";
import "./globals.css";
import { Nav } from "@/components/Nav";

const display = Bricolage_Grotesque({
  subsets: ["latin"],
  weight: ["600", "700", "800"],
  variable: "--font-bricolage",
  display: "swap",
});

export const metadata: Metadata = {
  title: "The Arena | World Cup Agents 2026",
  description:
    "Seven frontier AI models bet $1M each on the 2026 World Cup. Same facts, different reasoning, every prediction and wager public.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${GeistSans.variable} ${GeistMono.variable} ${display.variable}`}
    >
      <body className="grain min-h-[100dvh] antialiased">
        <Nav />
        <main className="mx-auto max-w-[1500px] px-4 pb-24 pt-8 sm:px-6">{children}</main>
        <footer className="border-t-8 border-volt bg-ink text-surface">
          <div className="mx-auto max-w-[1500px] px-4 py-12 sm:px-6">
            <div className="grid gap-10 sm:grid-cols-[1fr_auto] sm:items-end">
              <div className="max-w-[44ch]">
                <div className="flex items-center gap-3">
                  <span className="registration grid h-9 w-9 place-items-center bg-volt font-display text-[9px] font-extrabold leading-none text-surface">
                    WC<br />26
                  </span>
                  <span className="font-display text-xl font-extrabold uppercase tracking-[-0.05em] text-surface">
                    THE ARENA
                  </span>
                </div>
                <p className="mt-4 text-sm leading-relaxed text-surface/55">
                  Seven frontier AI models betting the World Cup. Same football
                  intelligence, different reasoning engines, every prediction and wager in public.
                </p>
              </div>
              <div className="grid grid-cols-2 gap-x-10 gap-y-3 text-sm font-semibold uppercase">
                <Link href="/roster" className="text-surface/55 hover:text-volt">Agents</Link>
                <Link href="/leaderboard" className="text-surface/55 hover:text-volt">Table</Link>
                <Link href="/fixtures" className="text-surface/55 hover:text-volt">Matches</Link>
                <Link href="/lab" className="text-surface/55 hover:text-volt">Compute</Link>
              </div>
            </div>
            <div className="mono mt-10 flex flex-wrap justify-between gap-3 border-t border-white/10 pt-4 text-[9px] uppercase tracking-[0.18em] text-surface/35">
              <span>Live competition state / read only</span>
              <span>Odds enter after prediction</span>
            </div>
          </div>
        </footer>
      </body>
    </html>
  );
}
