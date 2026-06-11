// Typed client for the FastAPI competition API. Server Components call these with
// an absolute base; the browser would hit /api/* via the Next rewrite proxy.

const API_BASE = process.env.API_PROXY ?? "http://127.0.0.1:8001";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`API ${path} -> ${res.status}`);
  return res.json() as Promise<T>;
}

// ---- shapes (mirror web/stats.py) ----------------------------------------

export interface AgentMeta {
  vendor: string;
  color: string;
  sigil: string;
  emblem: "rhythm" | "strategy" | "clock" | "plant" | "books" | "cursor" | "chart";
  persona_name: string;
  squad_number: number;
  position: string;
  tagline: string;
  blurb: string;
  play_style: string;
  signature_move: string;
  weakness: string;
  celebration: string;
  visual_motif: string;
  quote: string;
  ratings: {
    VISION: number;
    NERVE: number;
    CHAOS: number;
    VALUE: number;
    MEMORY: number;
    SWAG: number;
  };
}

export interface TeamSide {
  resolved: boolean;
  id: number | null;
  name: string;
  code: string | null;
  iso: string | null;
  group: string | null;
  fifa_rank: number | null;
}

export interface Odds {
  home: number;
  draw: number;
  away: number;
  bookmaker: string;
  captured_at: string;
}

export interface MatchResult {
  home_goals: number;
  away_goals: number;
  outcome: "home" | "draw" | "away" | null;
  went_extra_time: boolean;
  went_penalties: boolean;
  advanced_id: number | null;
}

export interface Fixture {
  id: number;
  stage: string;
  group: string | null;
  kickoff: string;
  venue: string | null;
  status: string;
  home: TeamSide;
  away: TeamSide;
  odds: Odds | null;
  result: MatchResult | null;
}

export interface Streak {
  type: "win" | "loss" | null;
  count: number;
}

export interface Accuracy {
  points: number;
  exact: number;
  outcomes: number;
  advance: number;
  graded: number;
  hit_rate: number;
}

export interface Competitor {
  model: string;
  meta: AgentMeta;
  bankroll: number;
  starting_bankroll: number;
  profit: number;
  active: boolean;
  lives_used: number;
  max_lives: number;
  bets_placed: number;
  passes: number;
  total_staked: number;
  avg_stake: number;
  avg_stake_pct: number;
  wins: number;
  losses: number;
  voids: number;
  win_rate: number;
  net_pnl: number;
  roi: number;
  streak: Streak;
  accuracy: Accuracy;
  telemetry: { calls: number; tokens: number; cost_usd: number };
  archetype: string;
}

export interface BankrollPoint {
  at: string;
  delta: number;
  balance_after: number;
  reason: string;
  fixture_id: number | null;
}

export interface LogEntry {
  fixture_id: number;
  fixture: { home: TeamSide; away: TeamSide; stage: string; kickoff: string } | null;
  pick: string | null;
  stake: number;
  odds_at_bet: number | null;
  reasoning: string;
  result: string | null;
  pnl: number | null;
}

export interface CompetitorDetail extends Competitor {
  bankroll_history: BankrollPoint[];
  log: LogEntry[];
}

export interface Overview {
  competitors: number;
  total_bankroll: number;
  starting_bankroll: number;
  fixtures_total: number;
  status_spread: Record<string, number>;
  first_kickoff: string | null;
  last_kickoff: string | null;
  days_to_kickoff: number | null;
  started: boolean;
  next_fixture: Fixture | null;
  totals: {
    bets: number;
    staked: number;
    predictions: number;
    calls: number;
    tokens: number;
    cost_usd: number;
  };
}

export interface AccuracyRow {
  model: string;
  meta: AgentMeta;
  points: number;
  exact: number;
  outcomes: number;
  advance: number;
  total: number;
  hit_rate: number;
}

export interface BoardEntry {
  model: string;
  meta: AgentMeta;
  prediction: {
    winner: string;
    p_home: number | null;
    p_draw: number | null;
    p_away: number | null;
    pred_home_goals: number | null;
    pred_away_goals: number | null;
    exp_home_goals: number | null;
    exp_away_goals: number | null;
    predicted_advance: string | null;
    confidence: number;
    reasoning: string;
  } | null;
  bet: {
    pick: string | null;
    stake: number;
    odds_at_bet: number | null;
    reasoning: string;
  } | null;
  settlement: { result: string; payout: number; pnl: number } | null;
}

export interface FixtureDetail extends Fixture {
  briefed: boolean;
  board: BoardEntry[];
}

export interface Telemetry {
  by_model: Array<{
    model_name: string;
    meta: AgentMeta;
    calls: number;
    tokens: number;
    cost_usd: number;
    cost_per_correct: number | null;
  }>;
  by_step: Array<{
    model_name: string;
    step: string;
    calls: number;
    tokens: number;
    cost_usd: number;
  }>;
  totals: { calls: number; tokens: number; cost_usd: number };
}

// ---- endpoints -----------------------------------------------------------

export const getOverview = () => get<Overview>("/api/overview");
export const getCompetitors = () => get<Competitor[]>("/api/competitors");
export const getCompetitor = (name: string) =>
  get<CompetitorDetail>(`/api/competitors/${encodeURIComponent(name)}`);
export const getBankrollBoard = () => get<Competitor[]>("/api/leaderboard/bankroll");
export const getAccuracyBoard = () => get<AccuracyRow[]>("/api/leaderboard/accuracy");
export const getFixtures = (q: { day?: string; stage?: string } = {}) => {
  const p = new URLSearchParams();
  if (q.day) p.set("day", q.day);
  if (q.stage) p.set("stage", q.stage);
  const qs = p.toString();
  return get<Fixture[]>(`/api/fixtures${qs ? `?${qs}` : ""}`);
};
export const getFixture = (id: number | string) => get<FixtureDetail>(`/api/fixtures/${id}`);
export const getToday = () => get<{ date: string; fixtures: Fixture[] }>("/api/today");
export const getTelemetry = () => get<Telemetry>("/api/telemetry");

// ---- secret Human Challenger (browser-only; same-origin so the session cookie flows) ----
// These run client-side via the Next /api proxy, NOT through the absolute server base, so
// the httpOnly auth cookie set by /unlock is sent on every subsequent call.

export interface ChallengerOdds {
  home: number;
  draw: number;
  away: number;
  bookmaker: string;
  captured_at: string;
}

export interface ChallengerFixture {
  fixture_id: number;
  stage: string;
  group: string | null;
  kickoff: string;
  lock_at: string;
  venue: string | null;
  home: string;
  away: string;
  is_knockout: boolean;
  has_odds: boolean;
  prediction: {
    winner: string;
    confidence: number;
    home_goals: number | null;
    away_goals: number | null;
    advances: string | null;
  } | null;
  odds: ChallengerOdds | null; // revealed only after a prediction exists
  bet: { pick: string; stake: number; odds_at_bet: number | null } | null;
}

export interface ChallengerState {
  name: string;
  max_stake_fraction: number;
  standing: CompetitorDetail;
  open_fixtures: ChallengerFixture[];
}

async function cfetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/challenger${path}`, {
    ...init,
    cache: "no-store",
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (res.status === 401) throw new ChallengerLocked();
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {}
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

/** Thrown when the session cookie is missing/invalid — the UI should show the passphrase gate. */
export class ChallengerLocked extends Error {}

export const challengerUnlock = (key: string) =>
  cfetch<{ ok: boolean; name: string }>("/unlock", {
    method: "POST",
    body: JSON.stringify({ key }),
  });
export const challengerLogout = () =>
  cfetch<{ ok: boolean }>("/logout", { method: "POST" });
export const challengerState = () => cfetch<ChallengerState>("/state");
export const challengerPredict = (body: {
  fixture_id: number;
  winner: string;
  confidence: number;
  home_goals?: number | null;
  away_goals?: number | null;
  advances?: string | null;
  reasoning?: string;
}) =>
  cfetch<{
    ok: boolean;
    bankroll: number;
    cap: number;
    open_stake: number;
    open_count: number;
    odds: ChallengerOdds | null;
  }>("/predict", { method: "POST", body: JSON.stringify(body) });
export const challengerBet = (body: {
  fixture_id: number;
  pick: string;
  stake: number;
  reasoning?: string;
}) =>
  cfetch<{ ok: boolean; pick: string; stake: number; odds_at_bet: number | null; cap: number }>(
    "/bet",
    { method: "POST", body: JSON.stringify(body) },
  );
