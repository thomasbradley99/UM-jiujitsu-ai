import React, { useEffect, useMemo, useState } from 'react';
import {
  fetchAiReview,
  fetchCrossEval,
  fetchGames,
  fetchRuns,
  formatPct,
  formatTime,
  type AIReview,
  type CrossEvalRow,
  type Game,
  type RunSummary,
} from '../services/labService';

type ReviewState = Record<string, { loading: boolean; error: string | null; data: AIReview | null }>;

function getWinner(game: Game): string {
  if (game.submissions.length === 0) return 'No clear winner';
  const counts = game.submissions.reduce<Record<string, number>>((acc, sub) => {
    acc[sub.submitter] = (acc[sub.submitter] ?? 0) + 1;
    return acc;
  }, {});
  const ordered = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  if (ordered.length < 2 || ordered[0][1] > ordered[1][1]) return ordered[0][0];
  return 'Draw';
}

function formatFightDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

function HeroStat({ label, value, tone = 'amber' }: { label: string; value: string; tone?: 'amber' | 'green' | 'blue' }) {
  const toneClass = tone === 'green'
    ? 'text-green-400 border-green-500/20 bg-green-500/5'
    : tone === 'blue'
    ? 'text-sky-400 border-sky-500/20 bg-sky-500/5'
    : 'text-[#FFB000] border-[#FFB000]/20 bg-[#FFB000]/5';

  return (
    <div className={`rounded-2xl border p-4 ${toneClass}`}>
      <p className="text-[10px] uppercase tracking-[0.25em] text-white/30">{label}</p>
      <p className="mt-2 text-2xl font-bold tracking-tight">{value}</p>
    </div>
  );
}

function MiniBarChart({
  items,
  formatter,
}: {
  items: { label: string; value: number; accent?: string }[];
  formatter?: (value: number) => string;
}) {
  const maxValue = Math.max(...items.map((item) => item.value), 1);

  return (
    <div className="flex flex-col gap-3">
      {items.map((item) => (
        <div key={item.label} className="grid grid-cols-[minmax(0,140px)_1fr_56px] items-center gap-3">
          <span className="truncate text-xs text-white/60">{item.label}</span>
          <div className="h-2.5 rounded-full bg-white/5 overflow-hidden">
            <div
              className="h-full rounded-full transition-all duration-700"
              style={{
                width: `${(item.value / maxValue) * 100}%`,
                background: item.accent ?? 'linear-gradient(90deg, rgba(255,176,0,0.9), rgba(255,176,0,0.35))',
              }}
            />
          </div>
          <span className="text-right text-xs font-mono text-white/40">
            {formatter ? formatter(item.value) : item.value}
          </span>
        </div>
      ))}
    </div>
  );
}

function ResultsSparkline({ items }: { items: { label: string; value: number }[] }) {
  const width = 360;
  const height = 120;
  const pad = 12;

  if (items.length === 0) return null;

  const points = items.map((item, index) => {
    const x = pad + (index / Math.max(items.length - 1, 1)) * (width - pad * 2);
    const y = pad + (1 - item.value) * (height - pad * 2);
    return { ...item, x, y };
  });

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-32">
      <defs>
        <linearGradient id="viz-line" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#FFB000" />
          <stop offset="100%" stopColor="#4ade80" />
        </linearGradient>
      </defs>
      <rect x="0" y="0" width={width} height={height} rx="18" fill="rgba(255,255,255,0.01)" />
      <path
        d={`M ${points.map((point) => `${point.x} ${point.y}`).join(' L ')}`}
        fill="none"
        stroke="url(#viz-line)"
        strokeWidth="3"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      {points.map((point) => (
        <g key={`${point.label}-${point.x}`}>
          <circle cx={point.x} cy={point.y} r="4" fill={point.value >= 0.8 ? '#4ade80' : '#FFB000'} />
          <text x={point.x} y={height - 8} textAnchor="middle" fontSize="9" fill="rgba(255,255,255,0.35)">
            {point.label}
          </text>
        </g>
      ))}
    </svg>
  );
}

function TechniqueDonut({ items }: { items: { label: string; value: number; color: string }[] }) {
  const total = items.reduce((sum, item) => sum + item.value, 0);
  const radius = 56;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;

  if (total === 0) return null;

  return (
    <div className="flex flex-col gap-4 lg:flex-row lg:items-center">
      <svg viewBox="0 0 160 160" className="h-44 w-44 shrink-0">
        <circle cx="80" cy="80" r={radius} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="18" />
        {items.map((item) => {
          const segment = (item.value / total) * circumference;
          const dashOffset = -offset;
          offset += segment;
          return (
            <circle
              key={item.label}
              cx="80"
              cy="80"
              r={radius}
              fill="none"
              stroke={item.color}
              strokeWidth="18"
              strokeDasharray={`${segment} ${circumference}`}
              strokeDashoffset={dashOffset}
              transform="rotate(-90 80 80)"
              strokeLinecap="butt"
            />
          );
        })}
        <text x="80" y="76" textAnchor="middle" fontSize="12" fill="rgba(255,255,255,0.4)">techniques</text>
        <text x="80" y="96" textAnchor="middle" fontSize="22" fontWeight="700" fill="#ffffff">{total}</text>
      </svg>

      <div className="flex-1 space-y-2">
        {items.map((item) => (
          <div key={item.label} className="flex items-center justify-between gap-3 text-sm">
            <div className="flex items-center gap-2 min-w-0">
              <span className="h-2.5 w-2.5 rounded-full shrink-0" style={{ backgroundColor: item.color }} />
              <span className="truncate text-white/65">{item.label}</span>
            </div>
            <span className="shrink-0 font-mono text-white/35">{item.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function SubmissionTimeline({ game }: { game: Game }) {
  const width = 420;
  const height = 48;
  const duration = Math.max(game.duration_sec || 1, 1);

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-14 rounded-xl bg-black/20">
      <line x1="18" y1="24" x2={width - 18} y2="24" stroke="rgba(255,255,255,0.12)" strokeWidth="2" />
      {game.submissions.map((sub) => {
        const x = 18 + (sub.timestamp / duration) * (width - 36);
        return (
          <g key={`${game.id}-${sub.timestamp}-${sub.technique}`}>
            <line x1={x} y1="15" x2={x} y2="33" stroke="#FFB000" strokeWidth="1.5" />
            <circle cx={x} cy="24" r="4.5" fill="#4ade80" />
            <title>{`${formatTime(sub.timestamp)} · ${sub.technique}`}</title>
          </g>
        );
      })}
      <text x="18" y="43" fontSize="9" fill="rgba(255,255,255,0.3)">0:00</text>
      <text x={width - 18} y="43" textAnchor="end" fontSize="9" fill="rgba(255,255,255,0.3)">
        {formatTime(duration)}
      </text>
    </svg>
  );
}

const VisualizationDashboard: React.FC = () => {
  const [games, setGames] = useState<Game[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [crossEval, setCrossEval] = useState<CrossEvalRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reviewOpen, setReviewOpen] = useState<Record<string, boolean>>({});
  const [reviews, setReviews] = useState<ReviewState>({});

  useEffect(() => {
    Promise.all([fetchGames(), fetchRuns(), fetchCrossEval()])
      .then(([gamesRes, runsRes, evalRes]) => {
        setGames(gamesRes);
        setRuns(runsRes);
        setCrossEval(evalRes);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const latestFightDate = useMemo(() => {
    const latest = [...games]
      .sort((a, b) => new Date(b.fight_date).getTime() - new Date(a.fight_date).getTime())[0];
    return latest ? formatFightDate(latest.fight_date) : '—';
  }, [games]);

  const fightSummaries = useMemo(() => {
    return [...games]
      .map((game) => {
        const relatedRuns = runs.filter((run) => run.video === game.id);
        const bestRun = [...relatedRuns].sort((a, b) => (b.peak_f1 ?? 0) - (a.peak_f1 ?? 0))[0];
        const evalRow = crossEval.find((row) => row.game === game.id);
        const winner = getWinner(game);
        const techniques = [...new Set(game.submissions.map((sub) => sub.technique))];
        return { game, winner, bestRun, evalRow, techniques };
      })
      .sort((a, b) => new Date(b.game.fight_date).getTime() - new Date(a.game.fight_date).getTime());
  }, [crossEval, games, runs]);

  const overview = useMemo(() => {
    const totalSubmissions = games.reduce((sum, game) => sum + game.submissions.length, 0);
    const bestRun = [...runs].sort((a, b) => (b.peak_f1 ?? 0) - (a.peak_f1 ?? 0))[0];
    const avgF1 = runs.length
      ? runs.reduce((sum, run) => sum + (run.peak_f1 ?? 0), 0) / runs.length
      : 0;
    return { totalFights: games.length, totalSubmissions, bestRun, avgF1 };
  }, [games, runs]);

  const submissionChart = useMemo(() => {
    return games.map((game) => ({
      label: game.id,
      value: game.submissions.length,
      accent: 'linear-gradient(90deg, rgba(255,176,0,0.95), rgba(255,255,255,0.25))',
    }));
  }, [games]);

  const performanceLine = useMemo(() => {
    return [...runs]
      .sort((a, b) => a.video.localeCompare(b.video) || a.id.localeCompare(b.id))
      .map((run) => ({ label: run.video, value: run.peak_f1 ?? 0 }));
  }, [runs]);

  const fighterWinRates = useMemo(() => {
    const stats = games.reduce<Record<string, { appearances: number; wins: number }>>((acc, game) => {
      const winner = getWinner(game);
      Object.keys(game.fighters).forEach((fighterKey) => {
        acc[fighterKey] = acc[fighterKey] ?? { appearances: 0, wins: 0 };
        acc[fighterKey].appearances += 1;
        if (winner === fighterKey) acc[fighterKey].wins += 1;
      });
      return acc;
    }, {});

    return Object.entries(stats)
      .map(([label, stat]) => ({
        label,
        value: stat.appearances === 0 ? 0 : stat.wins / stat.appearances,
        accent: 'linear-gradient(90deg, rgba(74,222,128,0.95), rgba(34,197,94,0.25))',
      }))
      .sort((a, b) => b.value - a.value);
  }, [games]);

  const techniqueBreakdown = useMemo(() => {
    const palette = ['#FFB000', '#4ade80', '#60a5fa', '#f472b6', '#a78bfa', '#f97316'];
    const counts = games.reduce<Record<string, number>>((acc, game) => {
      game.submissions.forEach((sub) => {
        const label = sub.technique.replace(/_/g, ' ');
        acc[label] = (acc[label] ?? 0) + 1;
      });
      return acc;
    }, {});

    return Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .map(([label, value], index) => ({ label, value, color: palette[index % palette.length] }));
  }, [games]);

  const toggleReview = async (gameId: string) => {
    const willOpen = !reviewOpen[gameId];
    setReviewOpen((state) => ({ ...state, [gameId]: willOpen }));
    if (!willOpen) return;

    const existing = reviews[gameId];
    if (existing?.loading || existing?.data) return;

    setReviews((state) => ({
      ...state,
      [gameId]: { loading: true, error: null, data: null },
    }));

    try {
      const review = await fetchAiReview(gameId);
      setReviews((state) => ({
        ...state,
        [gameId]: { loading: false, error: null, data: review },
      }));
    } catch (err) {
      setReviews((state) => ({
        ...state,
        [gameId]: {
          loading: false,
          error: err instanceof Error ? err.message : 'Failed to load AI review',
          data: null,
        },
      }));
    }
  };

  if (loading) {
    return (
      <p className="text-white/40 font-mono text-sm text-center mt-10 animate-pulse">
        Loading visualization dashboard…
      </p>
    );
  }

  if (error) {
    return (
      <p className="text-red-400 font-mono text-sm text-center mt-10">
        Error: {error}
      </p>
    );
  }

  return (
    <div className="space-y-6">
      <section className="rounded-[28px] border border-white/10 bg-[radial-gradient(circle_at_top_left,rgba(255,176,0,0.18),transparent_32%),linear-gradient(180deg,rgba(255,255,255,0.03),rgba(255,255,255,0.01))] p-6 shadow-[0_20px_80px_rgba(0,0,0,0.35)]">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-[10px] uppercase tracking-[0.35em] text-[#FFB000]/70">Visualization</p>
            <h2 className="mt-2 text-3xl font-bold text-white">Fight results, performance, and review cockpit</h2>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-white/55">
              The research lab now surfaces source-backed fight dates, richer charts, and Gemini-written fight reviews directly in the dashboard.
            </p>
          </div>
          <div className="rounded-2xl border border-white/10 bg-black/20 px-4 py-3 text-right">
            <p className="text-[10px] uppercase tracking-[0.3em] text-white/30">Latest fight date</p>
            <p className="mt-1 text-sm font-mono text-[#FFB000]">{latestFightDate}</p>
          </div>
        </div>

        <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <HeroStat label="Tracked Fights" value={String(overview.totalFights)} />
          <HeroStat label="Submissions Logged" value={String(overview.totalSubmissions)} tone="green" />
          <HeroStat label="Average Peak F1" value={formatPct(overview.avgF1)} tone="blue" />
          <HeroStat
            label="Top Arc"
            value={overview.bestRun ? `${overview.bestRun.video} · ${formatPct(overview.bestRun.peak_f1)}` : 'No runs'}
          />
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-[1.25fr_0.95fr]">
        <div className="rounded-[24px] border border-white/10 bg-black/40 p-5">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-[10px] uppercase tracking-[0.3em] text-white/25">Results trend</p>
              <h3 className="mt-1 text-lg font-semibold text-white">Peak F1 by fight</h3>
            </div>
            <span className="rounded-full border border-green-500/20 bg-green-500/10 px-3 py-1 text-[10px] uppercase tracking-[0.25em] text-green-300">
              Updated lab data
            </span>
          </div>
          <div className="mt-4">
            <ResultsSparkline items={performanceLine} />
          </div>
        </div>

        <div className="rounded-[24px] border border-white/10 bg-black/40 p-5">
          <p className="text-[10px] uppercase tracking-[0.3em] text-white/25">Fight density</p>
          <h3 className="mt-1 text-lg font-semibold text-white">Submissions per fight</h3>
          <div className="mt-4">
            <MiniBarChart items={submissionChart} />
          </div>
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-2">
        <div className="rounded-[24px] border border-white/10 bg-black/40 p-5">
          <p className="text-[10px] uppercase tracking-[0.3em] text-white/25">Fighter leaderboard</p>
          <h3 className="mt-1 text-lg font-semibold text-white">Win rate by fighter</h3>
          <div className="mt-4">
            <MiniBarChart items={fighterWinRates} formatter={(value) => formatPct(value)} />
          </div>
        </div>

        <div className="rounded-[24px] border border-white/10 bg-black/40 p-5">
          <p className="text-[10px] uppercase tracking-[0.3em] text-white/25">Technique mix</p>
          <h3 className="mt-1 text-lg font-semibold text-white">Submission breakdown donut</h3>
          <div className="mt-4">
            <TechniqueDonut items={techniqueBreakdown} />
          </div>
        </div>
      </section>

      <section>
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <p className="text-[10px] uppercase tracking-[0.3em] text-white/25">Latest results</p>
            <h3 className="mt-1 text-xl font-semibold text-white">Fight cards with dates, timelines, and Gemini review</h3>
          </div>
        </div>

        <div className="grid gap-5 lg:grid-cols-2">
          {fightSummaries.map(({ game, winner, bestRun, techniques, evalRow }) => {
            const reviewVisible = !!reviewOpen[game.id];
            const reviewState = reviews[game.id];
            return (
              <article
                key={game.id}
                className="rounded-[24px] border border-white/10 bg-[linear-gradient(180deg,rgba(255,255,255,0.03),rgba(255,255,255,0.01))] p-5"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-[10px] uppercase tracking-[0.3em] text-white/25">Fight result</p>
                    <h4 className="mt-2 text-lg font-semibold text-[#FFB000] uppercase tracking-wide">{game.id}</h4>
                    <p className="mt-1 text-xs text-white/35">Fight date {formatFightDate(game.fight_date)}</p>
                  </div>
                  <div className="rounded-2xl border border-[#FFB000]/20 bg-[#FFB000]/8 px-3 py-2 text-right">
                    <p className="text-[10px] uppercase tracking-[0.2em] text-white/30">Winner</p>
                    <p className="mt-1 text-sm font-semibold text-white">{winner}</p>
                  </div>
                </div>

                <p className="mt-4 text-sm leading-6 text-white/55">{game.description || 'Fight description unavailable.'}</p>

                <div className="mt-4 grid gap-3 sm:grid-cols-3">
                  <div className="rounded-2xl border border-white/8 bg-black/25 p-3">
                    <p className="text-[10px] uppercase tracking-[0.25em] text-white/25">Finish count</p>
                    <p className="mt-2 text-xl font-semibold text-white">{game.submissions.length}</p>
                  </div>
                  <div className="rounded-2xl border border-white/8 bg-black/25 p-3">
                    <p className="text-[10px] uppercase tracking-[0.25em] text-white/25">Best F1</p>
                    <p className="mt-2 text-xl font-semibold text-white">{bestRun ? formatPct(bestRun.peak_f1) : '—'}</p>
                  </div>
                  <div className="rounded-2xl border border-white/8 bg-black/25 p-3">
                    <p className="text-[10px] uppercase tracking-[0.25em] text-white/25">Cross-eval cells</p>
                    <p className="mt-2 text-xl font-semibold text-white">{evalRow?.cells.length ?? 0}</p>
                  </div>
                </div>

                <div className="mt-4">
                  <p className="mb-2 text-[10px] uppercase tracking-[0.25em] text-white/25">Submission timeline</p>
                  <SubmissionTimeline game={game} />
                </div>

                <div className="mt-4 flex flex-wrap gap-2">
                  {techniques.map((technique) => (
                    <span
                      key={technique}
                      className="rounded-full border border-[#FFB000]/20 bg-[#FFB000]/8 px-2.5 py-1 text-[10px] uppercase tracking-[0.2em] text-[#FFB000]"
                    >
                      {technique.replace(/_/g, ' ')}
                    </span>
                  ))}
                </div>

                <div className="mt-5 flex items-center justify-between gap-3">
                  <div className="text-xs text-white/40">
                    Updated from source {formatFightDate(game.source_updated_at)}
                  </div>
                  <button
                    type="button"
                    onClick={() => toggleReview(game.id)}
                    className="rounded-full border border-sky-400/20 bg-sky-500/10 px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.2em] text-sky-300 transition-colors hover:bg-sky-500/15"
                  >
                    {reviewVisible ? 'Hide review' : 'AI review'}
                  </button>
                </div>

                {reviewVisible && (
                  <div className="mt-4 rounded-2xl border border-sky-400/15 bg-sky-500/[0.06] p-4">
                    {reviewState?.loading && (
                      <p className="text-sm text-white/45 animate-pulse">Generating Gemini review…</p>
                    )}

                    {reviewState?.error && (
                      <p className="text-sm text-red-300">{reviewState.error}</p>
                    )}

                    {reviewState?.data && (
                      <div>
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <p className="text-[10px] uppercase tracking-[0.3em] text-sky-300/80">AI Review</p>
                            <h5 className="mt-2 text-base font-semibold text-white">{reviewState.data.headline}</h5>
                          </div>
                          <span className="rounded-full border border-white/10 px-3 py-1 text-[10px] uppercase tracking-[0.2em] text-white/45">
                            confidence {reviewState.data.confidence}
                          </span>
                        </div>
                        <p className="mt-3 text-sm leading-6 text-white/65">{reviewState.data.summary}</p>
                        <div className="mt-4 rounded-xl border border-white/6 bg-black/15 px-3 py-2 text-sm text-white/65">
                          <span className="font-semibold text-white">Winner call:</span> {reviewState.data.winner} · {reviewState.data.winner_reason}
                        </div>
                        <div className="mt-4 grid gap-4 md:grid-cols-3">
                          <div>
                            <p className="mb-2 text-[10px] uppercase tracking-[0.25em] text-white/25">Strengths</p>
                            <ul className="space-y-2 text-sm text-white/65">
                              {reviewState.data.strengths.map((item) => (
                                <li key={item} className="rounded-xl border border-white/6 bg-black/15 px-3 py-2">{item}</li>
                              ))}
                            </ul>
                          </div>
                          <div>
                            <p className="mb-2 text-[10px] uppercase tracking-[0.25em] text-white/25">Improvements</p>
                            <ul className="space-y-2 text-sm text-white/65">
                              {reviewState.data.improvements.map((item) => (
                                <li key={item} className="rounded-xl border border-white/6 bg-black/15 px-3 py-2">{item}</li>
                              ))}
                            </ul>
                          </div>
                          <div>
                            <p className="mb-2 text-[10px] uppercase tracking-[0.25em] text-white/25">Tactical focus</p>
                            <ul className="space-y-2 text-sm text-white/65">
                              {reviewState.data.tactical_focus.map((item) => (
                                <li key={item} className="rounded-xl border border-white/6 bg-black/15 px-3 py-2">{item}</li>
                              ))}
                            </ul>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </article>
            );
          })}
        </div>
      </section>
    </div>
  );
};

export default VisualizationDashboard;