import { NextResponse, type NextRequest } from "next/server";

// Visitor-tracking edge. Deliberately at /track (NOT /api/*, which next.config rewrites to the
// Python backend) so this runs in Next — the only layer that sees the real client IP behind the
// public proxy (Tailscale Funnel / nginx set x-forwarded-for). A once-per-session client beacon
// hits this; we resolve the visitor cookie + client IP + Challenger status and hand them to the
// secret-gated Python ingest. The IP leaves here only as a server-to-server field — never stored.

const API_PROXY = process.env.API_PROXY ?? "http://127.0.0.1:8001";
const INGEST_KEY = process.env.TRACK_INGEST_KEY ?? "";

const VID_COOKIE = "wc_vid";
const CHALLENGER_COOKIE = "wc_challenger"; // mirrors challenger.py:_COOKIE
const VID_MAX_AGE = 365 * 24 * 3600;

// Trust order: Cloudflare → standard proxy XFF (leftmost = original client) → nginx real-ip.
function clientIp(req: NextRequest): string | null {
  const cf = req.headers.get("cf-connecting-ip");
  if (cf) return cf.trim();
  const xff = req.headers.get("x-forwarded-for");
  if (xff) return xff.split(",")[0]!.trim();
  const real = req.headers.get("x-real-ip");
  if (real) return real.trim();
  return null;
}

export async function POST(req: NextRequest) {
  const existing = req.cookies.get(VID_COOKIE)?.value;
  const vid = existing ?? crypto.randomUUID();
  const isChallenger = req.cookies.get(CHALLENGER_COOKIE)?.value ? true : false;

  // Fire the ingest (best-effort; tracking must never break the page). Skipped when ingest is
  // unconfigured — the backend would 404 anyway.
  if (INGEST_KEY) {
    try {
      await fetch(`${API_PROXY}/api/track`, {
        method: "POST",
        headers: { "content-type": "application/json", "x-ingest-key": INGEST_KEY },
        body: JSON.stringify({ visitor_id: vid, ip: clientIp(req), is_challenger: isChallenger }),
        cache: "no-store",
      });
    } catch {
      // swallow — a tracking outage is invisible to the visitor
    }
  }

  const res = NextResponse.json({ ok: true });
  if (!existing) {
    res.cookies.set(VID_COOKIE, vid, {
      httpOnly: true,
      sameSite: "lax",
      secure: process.env.NODE_ENV === "production",
      maxAge: VID_MAX_AGE,
      path: "/",
    });
  }
  return res;
}
