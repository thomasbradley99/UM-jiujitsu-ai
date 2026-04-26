import React, { useEffect, useState } from 'react';
import {
  fetchRuns,
  fetchArc,
  formatPct,
  f1Color,
  type RunSummary,
  type Arc,
  type ArcIteration,
} from '../services/labService';

function Sparkline({ iterations }: { iterations: ArcIteration[] }) {
  const w = 120;
  const h = 32;
  const pad = 4;
  const pts = iterations.map((it, i) => {
    const x = pad + (i / Math.max(iterations.length - 1, 1)) * (w - pad * 2);
    const y = pad + (1 - it.f1) * (h - pad * 2);
    return `${x},${y}`;
  });

  return (
    <svg width={w} height={h} className="shrink-0">
      {pts.length > 1 && (
        <polyline
          points={pts.join(' ')}
          fill="none"
          stroke="#FFB000"
          strokeWidth="1.5"
          strokeLinejoin="round"
        />
      )}
      {iterations.map((it, i) => {
        const [x, y] = pts[i].split(',').map(Number);
        const cls = it.f1 >= 0.8 ? '#4ade80' : it.f1 >= 0.5 ? '#facc15' : '#f87171';
        return <circle key={i} cx={x} cy={y} r={3} fill={cls} />;
      })}
    </svg>
  );
}

function ArcCard({ summary }: { summary: RunSummary }) {
  const [arc, setArc] = useState<Arc | null>(null);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggle = async () => {
    if (!open && !arc) {
      setLoading(true);
      try {
        setArc(await fetchArc(summary.id));
      } catch (e: any) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    }
    setOpen((v) => !v);
  };

  return (
    <div className="bg-black/60 border border-white/10 rounded-lg overflow-hidden">
      {/* Header */}
      <button
        type="button"
        className="w-full flex items-center gap-4 px-4 py-3 hover:bg-white/5 transition-colors text-left"
        onClick={toggle}
      >
        <div className="flex-1 min-w-0">
          <h3 className="font-mono text-sm font-bold text-[#FFB000] truncate">{summary.label}</h3>
          <p className="text-white/40 text-[11px] font-mono mt-0.5">
            {summary.model} · {summary.n_iterations} iterations · video: {summary.video}
          </p>
        </div>
        <div className="text-right shrink-0">
          <div className={`font-mono text-sm font-bold ${f1Color(summary.peak_f1)}`}>
            peak F1 {formatPct(summary.peak_f1)}
          </div>
        </div>
        <span className="text-white/30 font-mono">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="border-t border-white/5 px-4 pb-4">
          {loading && (
            <p className="text-white/40 font-mono text-xs text-center mt-4 animate-pulse">
              Loading arc detail…
            </p>
          )}
          {error && (
            <p className="text-red-400 font-mono text-xs mt-4">Error: {error}</p>
          )}
          {arc && (
            <>
              {/* Sparkline */}
              <div className="flex items-center gap-3 mt-3 mb-3">
                <span className="text-white/30 font-mono text-[10px] uppercase tracking-widest">F1 trend</span>
                <Sparkline iterations={arc.iterations} />
              </div>

              {/* Iteration table */}
              <div className="overflow-x-auto">
                <table className="w-full text-xs font-mono">
                  <thead>
                    <tr className="border-b border-white/10">
                      {['Iter', 'F1', 'Prec', 'Recall', 'Matched', 'Halls', 'Chars', 'Prompt ID'].map(
                        (h) => (
                          <th
                            key={h}
                            className="text-left text-white/30 uppercase tracking-wider text-[10px] pb-2 pr-4"
                          >
                            {h}
                          </th>
                        )
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {arc.iterations.map((it) => (
                      <tr
                        key={it.iteration}
                        className="border-b border-white/5 last:border-0 hover:bg-white/5"
                      >
                        <td className="py-1.5 pr-4 text-white/60">v{it.iteration}</td>
                        <td className={`pr-4 font-bold ${f1Color(it.f1)}`}>
                          {formatPct(it.f1)}
                        </td>
                        <td className="pr-4 text-white/60">{formatPct(it.precision)}</td>
                        <td className="pr-4 text-white/60">{formatPct(it.recall)}</td>
                        <td className="pr-4 text-white/60">
                          {it.n_matched}/{it.n_gt}
                        </td>
                        <td
                          className={`pr-4 ${
                            it.n_hallucinations === 0
                              ? 'text-green-400'
                              : it.n_hallucinations <= 2
                              ? 'text-yellow-400'
                              : 'text-red-400'
                          }`}
                        >
                          {it.n_hallucinations}
                        </td>
                        <td className="pr-4 text-white/40">{it.prompt_chars}</td>
                        <td className="text-white/30 truncate max-w-[120px]">
                          {it.prompt_version_id.slice(0, 16)}…
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

const ArcExplorer: React.FC = () => {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchRuns()
      .then(setRuns)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading)
    return (
      <p className="text-white/40 font-mono text-sm text-center mt-10 animate-pulse">
        Loading arcs…
      </p>
    );
  if (error)
    return (
      <p className="text-red-400 font-mono text-sm text-center mt-10">
        Error: {error}
      </p>
    );
  if (runs.length === 0)
    return (
      <p className="text-white/30 font-mono text-sm text-center mt-10 italic">
        No flywheel arcs found.
      </p>
    );

  return (
    <div className="flex flex-col gap-3">
      {runs.map((r) => (
        <ArcCard key={r.id} summary={r} />
      ))}
    </div>
  );
};

export default ArcExplorer;
