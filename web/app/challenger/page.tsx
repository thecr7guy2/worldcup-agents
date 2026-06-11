import type { Metadata } from "next";
import { ChallengerConsole } from "@/components/ChallengerConsole";

// Secret page: not linked anywhere, and kept out of search indexes. Reaching the URL alone
// reveals nothing — the console gates on the passphrase before any data is shown.
export const metadata: Metadata = {
  title: "Challenger",
  robots: { index: false, follow: false },
};

export default function ChallengerPage() {
  return <ChallengerConsole />;
}
