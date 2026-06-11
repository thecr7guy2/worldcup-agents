"use client";

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";

// The secret entrance. Typing the Konami code (↑ ↑ ↓ ↓ ← → ← → B A) anywhere on the site
// navigates to the hidden /challenger console. There is no visible link to it anywhere —
// the gesture is the only way to discover the door, and the passphrase is the only way
// through it. Mounted once in the root layout.
const SEQUENCE = [
  "ArrowUp",
  "ArrowUp",
  "ArrowDown",
  "ArrowDown",
  "ArrowLeft",
  "ArrowRight",
  "ArrowLeft",
  "ArrowRight",
  "b",
  "a",
];

export function KonamiUnlock() {
  const router = useRouter();
  const progress = useRef(0);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      // Ignore typing inside inputs so the passphrase field etc. never trips it.
      const el = e.target as HTMLElement | null;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable))
        return;

      const expected = SEQUENCE[progress.current];
      if (e.key.toLowerCase() === expected.toLowerCase()) {
        progress.current += 1;
        if (progress.current === SEQUENCE.length) {
          progress.current = 0;
          router.push("/challenger");
        }
      } else {
        // Allow a fresh start if the wrong key happens to be the first key of the sequence.
        progress.current = e.key === SEQUENCE[0] ? 1 : 0;
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router]);

  return null;
}
