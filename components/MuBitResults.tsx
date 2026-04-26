import React, { useEffect, useMemo, useState } from 'react';
import { fetchArc, formatPct, type Arc } from '../services/labService';

type ArcLoad = {
  loading: boolean;
  error: string | null;
  data: Arc | null;
};

function StatCard({
  label,
  value,
  sublabel,
  tone = 'amber',
}: {
  label: string;
  value: string;
  sublabel?: string;
  tone?: 'amber' | 'green' | 'red' | 'blue';
}) {
  const toneClass = tone === 'green'
    ? 'text-green-400 border-green-500/20 bg-green-500/5'
    : tone === 'red'
    ? 'text-red-400 border-red-500/20 bg-red-500/5'
    : tone === 'blue'
    ? 'text-sky-400 border-sky-500/20 bg-sky-500/5'
    : 'text-[#FFB000] border-[#FFB000]/20 bg-[#FFB000]/5';

  return (
    <div className={`rounded-2xl border p-4 ${toneClass}`}>
      <p className="text-[10px] uppercase tracking-[0.25em] text-white/30">{label}</p>
      <p className="mt-2 text-2xl font-bold tracking-tight">{value}</p>
      {sublabel && <p className="mt-1 text-xs text-white/45">{sublabel}</p>}
    </div>
  );
}

function ComparisonBar({
  label,
  benchmark,
  optimized,
  invert = false,
}: {
  label: string;
  benchmark: number;
  optimized: number;
  invert?: boolean;
}) {
  const max = Math.max(benchmark, optimized, 1);
  const better = invert ? optimized < benchmark : optimized > benchmark;

  return (
    <div className="space-y-2 rounded-2xl border border-white/10 bg-black/30 p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs uppercase tracking-[0.25em] text-white/35">{label}</p>
        <span className={`text-[11px] font-semibold ${better ? 'text-green-400' : 'text-yellow-300'}`}>
          {better ? 'MuBit ahead' : 'Closer run'}
        </span>
      </div>
      <div className="space-y-2">
        <div className="grid grid-cols-[120px_1fr_56px] items-center gap-3">
          <span className="text-xs text-white/55">Benchmark</span>
          <div className="h-2.5 overflow-hidden rounded-full bg-white/5">
            <div
              className="h-full rounded-full bg-white/30 transition-all duration-700"
              style={{ width: `${(benchmark / max) * 100}%` }}
            />
          </div>
          <span className="text-right font-mono text-xs text-white/40">{benchmark.toFixed(2)}</span>
        </div>
        <div className="grid grid-cols-[120px_1fr_56px] items-center gap-3">
          <span className="text-xs text-white/55">MuBit optimized</span>
          <div className="h-2.5 overflow-hidden rounded-full bg-white/5">
            <div
              className={`h-full rounded-full transition-all duration-700 ${invert ? 'bg-sky-400/80' : 'bg-green-400/80'}`}
              style={{ width: `${(optimized / max) * 100}%` }}
            />
          </div>
          <span className="text-right font-mono text-xs text-white/40">{optimized.toFixed(2)}</span>
        </div>
      </div>
    </div>
  );
}

function ArcTrend({
  title,
  arc,
  stroke,
}: {
  title: string;
  arc: Arc;
  stroke: string;
}) {
  const width = 300;
  const height = 90;
  const pad = 12;
  const points = arc.iterations.map((it, index) => {
    const x = pad + (index / Math.max(arc.iterations.length - 1, 1)) * (width - pad * 2);
    const y = pad + (1 - it.f1) * (height - pad * 2);
    return { x, y, it };
  });

  return (
    <div className="rounded-2xl border border-white/10 bg-black/30 p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-semibold text-white">{title}</p>
        <span className="text-xs text-white/35">{arc.iterations.length} iterations</span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="mt-3 h-28 w-full">
        <line x1={pad} y1={height - pad} x2={width - pad} y2={height - pad} stroke="rgba(255,255,255,0.08)" />
        <line x1={pad} y1={pad} x2={pad} y2={height - pad} stroke="rgba(255,255,255,0.08)" />
        <path
          d={`M ${points.map((point) => `${point.x} ${point.y}`).join(' L ')}`}
          fill="none"
          stroke={stroke}
          strokeWidth="3"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        {points.map((point) => (
          <g key={`${arc.id}-${point.it.iteration}`}>
            <circle cx={point.x} cy={point.y} r="4" fill={stroke} />
            <text x={point.x} y={height - 2} textAnchor="middle" fontSize="9" fill="rgba(255,255,255,0.35)">
              v{point.it.iteration}
            </text>
          </g>
        ))}
      </svg>
      <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-white/45">
        <span>Start {formatPct(arc.iterations[0]?.f1 ?? 0)}</span>
        <span className="text-right">Best {formatPct(Math.max(...arc.iterations.map((it) => it.f1), 0))}</span>
      </div>
    </div>
  );
}

const MUBIT_WRITEUP = [
  'MuBit owns the optimizable DOMAIN RULES layer, not the video model itself.',
  'After feedback from TP / FP / FN rationales, the optimizer added temporal requirements and distinction criteria.',
  'That shift raises recall while also pulling down hallucinations once the rules better separate real finishes from neutral resets.',
];

const MuBitResults: React.FC = () => {
  const [benchmarkArc, setBenchmarkArc] = useState<ArcLoad>({ loading: true, error: null, data: null });
  const [optimizedArc, setOptimizedArc] = useState<ArcLoad>({ loading: true, error: null, data: null });

  useEffect(() => {
    fetchArc('naive-ryan-thomas')
      .then((data) => setBenchmarkArc({ loading: false, error: null, data }))
      .catch((e: Error) => setBenchmarkArc({ loading: false, error: e.message, data: null }));

    fetchArc('handtuned-ryan-thomas')
      .then((data) => setOptimizedArc({ loading: false, error: null, data }))
      .catch((e: Error) => setOptimizedArc({ loading: false, error: e.message, data: null }));
  }, []);

  const comparison = useMemo(() => {
    if (!benchmarkArc.data || !optimizedArc.data) return null;

    const benchmarkBest = benchmarkArc.data.iterations.reduce((best, it) => (it.f1 > best.f1 ? it : best), benchmarkArc.data.iterations[0]);
    const optimizedBest = optimizedArc.data.iterations.reduce((best, it) => (it.f1 > best.f1 ? it : best), optimizedArc.data.iterations[0]);
    const baselineV1 = optimizedArc.data.iterations[0];
    const optimizedV2 = optimizedArc.data.iterations[1] ?? optimizedBest;

    return {
      benchmarkBest,
      optimizedBest,
      baselineV1,
      optimizedV2,
      f1LiftVsBenchmark: optimizedBest.f1 - benchmarkBest.f1,
      hallucinationDropVsBenchmark: benchmarkBest.n_hallucinations - optimizedBest.n_hallucinations,
      f1LiftFromRewrite: optimizedV2.f1 - baselineV1.f1,
      hallucinationDropFromRewrite: baselineV1.n_hallucinations - optimizedV2.n_hallucinations,
    };
  }, [benchmarkArc.data, optimizedArc.data]);

  if (benchmarkArc.loading || optimizedArc.loading) {
    return (
      <p className="mt-10 text-center font-mono text-sm text-white/40 animate-pulse">
        Loading MuBit comparison…
      </p>
    );
  }

  if (benchmarkArc.error || optimizedArc.error || !comparison || !benchmarkArc.data || !optimizedArc.data) {
    return (
      <p className="mt-10 text-center font-mono text-sm text-red-400">
        Error: {benchmarkArc.error || optimizedArc.error || 'MuBit comparison data unavailable'}
      </p>
    );
  }

  return (
    <div className="space-y-6">
      <section className="rounded-[28px] border border-white/10 bg-[radial-gradient(circle_at_top_left,rgba(74,222,128,0.14),transparent_32%),linear-gradient(180deg,rgba(255,255,255,0.03),rgba(255,255,255,0.01))] p-6 shadow-[0_20px_80px_rgba(0,0,0,0.35)]">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-[10px] uppercase tracking-[0.35em] text-green-300/80">MuBit results</p>
            <h2 className="mt-2 text-3xl font-bold text-white">How MuBit improves results vs the benchmark</h2>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-white/55">
              This tab compares the naive benchmark arc against the MuBit-driven optimization arc for Ryan vs Thomas, focusing on F1 lift and hallucination reduction.
            </p>
          </div>
          <div className="rounded-2xl border border-white/10 bg-black/20 px-4 py-3 text-right">
            <p className="text-[10px] uppercase tracking-[0.3em] text-white/30">Using local MuBit artifacts</p>
            <p className="mt-1 text-sm font-mono text-[#FFB000]">Ryan vs Thomas</p>
          </div>
        </div>

        <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <StatCard
            label="Best MuBit F1"
            value={formatPct(comparison.optimizedBest.f1)}
            sublabel={`v${comparison.optimizedBest.iteration} · ${comparison.optimizedBest.prompt_version_id.slice(0, 12)}…`}
            tone="green"
          />
          <StatCard
            label="Benchmark Best F1"
            value={formatPct(comparison.benchmarkBest.f1)}
            sublabel={`v${comparison.benchmarkBest.iteration} naive seed`}
            tone="amber"
          />
          <StatCard
            label="F1 Lift Vs Benchmark"
            value={formatPct(comparison.f1LiftVsBenchmark)}
            sublabel="Best optimized minus best naive"
            tone="blue"
          />
          <StatCard
            label="Hallucinations Reduced"
            value={String(comparison.hallucinationDropVsBenchmark)}
            sublabel="Benchmark FP count minus MuBit best FP count"
            tone="green"
          />
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-2">
        <ArcTrend title="Benchmark arc (naive seed)" arc={benchmarkArc.data} stroke="#94a3b8" />
        <ArcTrend title="MuBit-optimized arc" arc={optimizedArc.data} stroke="#4ade80" />
      </section>

      <section className="grid gap-6 xl:grid-cols-2">
        <ComparisonBar
          label="Best F1 comparison"
          benchmark={comparison.benchmarkBest.f1}
          optimized={comparison.optimizedBest.f1}
        />
        <ComparisonBar
          label="Best hallucination count"
          benchmark={comparison.benchmarkBest.n_hallucinations}
          optimized={comparison.optimizedBest.n_hallucinations}
          invert
        />
      </section>

      <section className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
        <div className="rounded-[24px] border border-white/10 bg-black/40 p-5">
          <p className="text-[10px] uppercase tracking-[0.3em] text-white/25">Rewrite effect</p>
          <h3 className="mt-1 text-lg font-semibold text-white">MuBit v1 → v2 improvement</h3>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <StatCard
              label="Baseline v1"
              value={`${formatPct(comparison.baselineV1.f1)} / ${comparison.baselineV1.n_hallucinations} FP`}
              sublabel="Hand-tuned starting point before optimizer rewrite"
              tone="amber"
            />
            <StatCard
              label="After first rewrite"
              value={`${formatPct(comparison.optimizedV2.f1)} / ${comparison.optimizedV2.n_hallucinations} FP`}
              sublabel="First candidate returned after improve()"
              tone="green"
            />
          </div>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <StatCard
              label="F1 gain from rewrite"
              value={formatPct(comparison.f1LiftFromRewrite)}
              sublabel="v2 minus v1"
              tone="blue"
            />
            <StatCard
              label="Hallucination drop"
              value={String(comparison.hallucinationDropFromRewrite)}
              sublabel="v1 FP count minus v2 FP count"
              tone="green"
            />
          </div>
        </div>

        <div className="rounded-[24px] border border-white/10 bg-black/40 p-5">
          <p className="text-[10px] uppercase tracking-[0.3em] text-white/25">What MuBit changed</p>
          <h3 className="mt-1 text-lg font-semibold text-white">Optimizer impact summary</h3>
          <div className="mt-4 space-y-3">
            {MUBIT_WRITEUP.map((note) => (
              <div key={note} className="rounded-2xl border border-white/8 bg-white/[0.02] px-4 py-3 text-sm leading-6 text-white/65">
                {note}
              </div>
            ))}
            <div className="rounded-2xl border border-green-500/15 bg-green-500/[0.05] px-4 py-3 text-sm leading-6 text-white/65">
              In the local arc data, the optimized path moves from <span className="font-semibold text-white">{formatPct(comparison.baselineV1.f1)}</span> F1 with <span className="font-semibold text-white">{comparison.baselineV1.n_hallucinations}</span> hallucinations to <span className="font-semibold text-white">{formatPct(comparison.optimizedBest.f1)}</span> F1 with <span className="font-semibold text-white">{comparison.optimizedBest.n_hallucinations}</span> hallucinations at its peak.
            </div>
          </div>
        </div>
      </section>

      <section className="rounded-[24px] border border-white/10 bg-black/40 p-5">
        <p className="text-[10px] uppercase tracking-[0.3em] text-white/25">Iteration table</p>
        <h3 className="mt-1 text-lg font-semibold text-white">Benchmark vs MuBit side-by-side</h3>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[760px] text-xs font-mono">
            <thead>
              <tr className="border-b border-white/10 text-white/35">
                <th className="pb-2 text-left uppercase tracking-wider">Arc</th>
                <th className="pb-2 text-left uppercase tracking-wider">Iter</th>
                <th className="pb-2 text-left uppercase tracking-wider">F1</th>
                <th className="pb-2 text-left uppercase tracking-wider">Precision</th>
                <th className="pb-2 text-left uppercase tracking-wider">Recall</th>
                <th className="pb-2 text-left uppercase tracking-wider">Matched</th>
                <th className="pb-2 text-left uppercase tracking-wider">Hallucinations</th>
                <th className="pb-2 text-left uppercase tracking-wider">Chars</th>
              </tr>
            </thead>
            <tbody>
              {[...benchmarkArc.data.iterations.map((it) => ({ ...it, arc: 'Benchmark' })), ...optimizedArc.data.iterations.map((it) => ({ ...it, arc: 'MuBit' }))].map((it) => (
                <tr key={`${it.arc}-${it.iteration}-${it.prompt_version_id}`} className="border-b border-white/5 text-white/65">
                  <td className="py-2 pr-4">{it.arc}</td>
                  <td className="py-2 pr-4">v{it.iteration}</td>
                  <td className={`py-2 pr-4 font-semibold ${it.f1 >= 0.8 ? 'text-green-400' : it.f1 >= 0.5 ? 'text-yellow-300' : 'text-red-400'}`}>
                    {formatPct(it.f1)}
                  </td>
                  <td className="py-2 pr-4">{formatPct(it.precision)}</td>
                  <td className="py-2 pr-4">{formatPct(it.recall)}</td>
                  <td className="py-2 pr-4">{it.n_matched}/{it.n_gt}</td>
                  <td className="py-2 pr-4">{it.n_hallucinations}</td>
                  <td className="py-2 pr-4 text-white/35">{it.prompt_chars}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
};

export default MuBitResults;
