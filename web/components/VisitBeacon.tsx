"use client";

import { useEffect } from "react";

// Fires one /track ping per browser session so the visitor-geography widget can count unique
// watchers and where they're tuning in from. sessionStorage-guarded (one hit per tab session),
// fully fire-and-forget — never blocks or surfaces anything to the visitor.
export function VisitBeacon() {
  useEffect(() => {
    try {
      if (sessionStorage.getItem("wc_tracked")) return;
      sessionStorage.setItem("wc_tracked", "1");
    } catch {
      // private mode / storage disabled — fall through and still ping once per load
    }
    fetch("/track", { method: "POST", cache: "no-store", keepalive: true }).catch(() => {});
  }, []);

  return null;
}
