/**
 * Research Lab data service.
 * Fetches BJJ experiment data from the /api/lab/* endpoints served by server.js.
 * Types mirror website/SCHEMA.md exactly.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ArcSummary {
  id: string;
  label: string;
  peak_f1: number | null;
}

export interface Manifest {
  built_at: string;
  games: string[];
  arcs: ArcSummary[];
  cross_eval_games: string[];
}

export interface Fighter {
  visual: string;
  role?: string;
  ai_descriptor?: string;
}

export interface Submission {
  timestamp: number;
  technique: string;
  submitter: string;
  submittee: string;
  notes?: string;
}

export interface Game {
  id: string;
  fight_date: string;
  source_updated_at: string;
  duration_sec: number;
  description: string;
  fighters: Record<string, Fighter>;
  submissions: Submission[];
  video_url: string | null;
}

export interface RunSummary {
  id: string;
  label: string;
  video: string;
  model: string;
  n_iterations: number;
  peak_f1: number | null;
}

export interface ArcIteration {
  iteration: number;
  prompt_version_id: string;
  f1: number;
  precision: number;
  recall: number;
  n_gt: number;
  n_pred: number;
  n_matched: number;
  n_hallucinations: number;
  candidate_version_id: string | null;
  activated: boolean;
  prompt_chars: number;
}

export interface Arc {
  id: string;
  label: string;
  video: string;
  model: string;
  iterations: ArcIteration[];
}

export interface CrossEvalCell {
  label: string;
  prompt_version_id: string;
  f1: number;
  precision: number;
  recall: number;
  technique_acc: number;
  submitter_acc: number;
  n_gt: number;
  matched: number;
  hallucinations: number;
}

export interface CrossEvalRow {
  game: string;
  cells: CrossEvalCell[];
}

export interface AIReview {
  headline: string;
  summary: string;
  winner: string;
  winner_reason: string;
  strengths: string[];
  improvements: string[];
  tactical_focus: string[];
  confidence: 'high' | 'medium' | 'low';
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

const BASE = '/api/lab';

async function labFetch<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`Lab API [${res.status}] ${path}: ${body}`);
  }
  return res.json() as Promise<T>;
}

export const fetchManifest = (): Promise<Manifest> =>
  labFetch<Manifest>('/manifest');

export const fetchGames = (): Promise<Game[]> =>
  labFetch<Game[]>('/games');

export const fetchGame = (id: string): Promise<Game> =>
  labFetch<Game>(`/games/${id}`);

export const fetchRuns = (): Promise<RunSummary[]> =>
  labFetch<RunSummary[]>('/runs');

export const fetchArc = (id: string): Promise<Arc> =>
  labFetch<Arc>(`/runs/${id}`);

export const fetchCrossEval = (): Promise<CrossEvalRow[]> =>
  labFetch<CrossEvalRow[]>('/cross-eval');

export const fetchAiReview = (gameId: string): Promise<AIReview> =>
  fetch(`${BASE}/review/${gameId}`, { method: 'POST' }).then(async (res) => {
    if (!res.ok) {
      const body = await res.text().catch(() => '');
      throw new Error(`Lab API [${res.status}] /review/${gameId}: ${body}`);
    }
    return res.json() as Promise<AIReview>;
  });

export const triggerBuild = (): Promise<{ ok: boolean; output: string }> =>
  fetch(`${BASE}/build`, { method: 'POST' }).then((r) => r.json());

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export const formatPct = (v: number | null | undefined): string =>
  v === null || v === undefined ? '—' : `${Math.round(v * 100)}%`;

export const formatTime = (secs: number): string => {
  const m = Math.floor(secs / 60)
    .toString()
    .padStart(2, '0');
  const s = Math.floor(secs % 60)
    .toString()
    .padStart(2, '0');
  return `${m}:${s}`;
};

export const f1Color = (v: number | null | undefined): string => {
  if (v === null || v === undefined) return 'text-gray-500';
  if (v >= 0.8) return 'text-green-400';
  if (v >= 0.5) return 'text-yellow-400';
  return 'text-red-400';
};
