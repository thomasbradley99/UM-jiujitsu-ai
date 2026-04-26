import React, { useCallback, useEffect, useRef, useState } from 'react';

// ─── Existing types (unchanged) ────────────────────────────────────────────

export interface TimestampEvent {
  timestamp: number;
  title: string;
  description: string;
}

// ─── SSE stream types (mirror backend StreamFrame) ─────────────────────────

interface DetectedEvent {
  event_id: string;
  timestamp_sec: number;
  technique: string;
  submitter: string;
  submittee: string;
  confidence: number;
  confidence_pct: string;
  notes: string | null;
}

interface LiveMetrics {
  iteration: number;
  prompt_label: string;
  precision: number;
  recall: number;
  f1: number;
  f1_pct: string;
  n_gt: number;
  n_pred: number;
  matched: number;
  hallucinations: number;
  hallucination_rate: number;
  activated: boolean;
}

type FrameType = 'event' | 'metrics' | 'complete' | 'heartbeat';

interface StreamFrame {
  frame_type: FrameType;
  elapsed_sec: number;
  total_events: number;
  events: DetectedEvent[];
  metrics_history: LiveMetrics[];
  message?: string;
}

interface ArcOption {
  id: string;
  label: string;
  peak_f1: number | null;
}

// ─── Helpers ───────────────────────────────────────────────────────────────

const fmtTime = (seconds: number): string => {
  const m = Math.floor(seconds / 60).toString().padStart(2, '0');
  const s = Math.floor(seconds % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
};

const pct = (v: number): string => `${Math.round(v * 100)}%`;

const f1Color = (v: number): string => {
  if (v >= 0.8) return '#4ade80';
  if (v >= 0.5) return '#facc15';
  return '#f87171';
};

// ─── Sub-components ────────────────────────────────────────────────────────

/** Animated horizontal metric bar (P / R / F1). */
function MetricBar({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="flex items-center gap-2 text-xs font-mono">
      <span className="w-7 text-white/40 uppercase shrink-0">{label}</span>
      <div className="flex-1 h-3 bg-white/10 rounded-sm overflow-hidden relative">
        <div
          className="h-full rounded-sm transition-all duration-700 ease-out"
          style={{ width: `${Math.round(value * 100)}%`, backgroundColor: color }}
        />
      </div>
      <span className="w-9 text-right shrink-0" style={{ color }}>{pct(value)}</span>
    </div>
  );
}

/** F1 trend sparkline — animates as new iterations arrive. */
function F1Sparkline({ history }: { history: LiveMetrics[] }) {
  const W = 200;
  const H = 40;
  const PAD = 4;

  if (history.length === 0) {
    return (
      <svg width={W} height={H} className="opacity-30">
        <line x1={PAD} y1={H / 2} x2={W - PAD} y2={H / 2} stroke="#FFB000" strokeWidth="1" strokeDasharray="3 3" />
      </svg>
    );
  }

  const pts = history.map((m, i) => {
    const x = PAD + (i / Math.max(history.length - 1, 1)) * (W - PAD * 2);
    const y = PAD + (1 - m.f1) * (H - PAD * 2);
    return { x, y, m };
  });

  const polylinePoints = pts.map((p) => `${p.x},${p.y}`).join(' ');

  return (
    <svg width={W} height={H} className="shrink-0">
      {/* Zero and 100% guide lines */}
      <line x1={PAD} y1={PAD} x2={W - PAD} y2={PAD} stroke="#ffffff" strokeWidth="0.5" strokeOpacity="0.1" />
      <line x1={PAD} y1={H - PAD} x2={W - PAD} y2={H - PAD} stroke="#ffffff" strokeWidth="0.5" strokeOpacity="0.1" />
      {pts.length > 1 && (
        <polyline
          points={polylinePoints}
          fill="none"
          stroke="#FFB000"
          strokeWidth="1.5"
          strokeLinejoin="round"
        />
      )}
      {pts.map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r={3.5} fill={f1Color(p.m.f1)} />
      ))}
    </svg>
  );
}

/** Technique frequency bar chart. */
function TechniqueChart({ events }: { events: DetectedEvent[] }) {
  const counts: Record<string, number> = {};
  for (const ev of events) counts[ev.technique] = (counts[ev.technique] ?? 0) + 1;

  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const maxCount = entries[0]?.[1] ?? 1;

  if (entries.length === 0) return null;

  return (
    <div className="flex flex-col gap-1">
      {entries.map(([tech, count]) => (
        <div key={tech} className="flex items-center gap-2 text-[10px] font-mono">
          <span className="w-28 truncate text-white/60 shrink-0">{tech}</span>
          <div className="flex-1 h-2.5 bg-white/10 rounded-sm overflow-hidden">
            <div
              className="h-full rounded-sm transition-all duration-500"
              style={{ width: `${(count / maxCount) * 100}%`, backgroundColor: '#FFB000' }}
            />
          </div>
          <span className="w-4 text-right text-[#FFB000] shrink-0">{count}</span>
        </div>
      ))}
    </div>
  );
}

/** Confidence timeline — dots on a horizontal track. */
function ConfidenceTimeline({
  events,
  duration,
}: {
  events: DetectedEvent[];
  duration: number;
}) {
  const W = '100%';
  const H = 28;
  const maxSec = duration || Math.max(...events.map((e) => e.timestamp_sec), 60);

  return (
    <svg width={W} height={H} className="w-full">
      <line x1="0" y1={H / 2} x2="100%" y2={H / 2} stroke="#ffffff" strokeOpacity="0.1" strokeWidth="1" />
      {events.map((ev) => {
        const xPct = (ev.timestamp_sec / maxSec) * 100;
        const col = f1Color(ev.confidence);
        return (
          <g key={ev.event_id}>
            <circle
              cx={`${xPct}%`}
              cy={H / 2}
              r={5}
              fill={col}
              fillOpacity="0.85"
            />
            <title>{`${fmtTime(ev.timestamp_sec)} · ${ev.technique} · ${ev.confidence_pct}`}</title>
          </g>
        );
      })}
    </svg>
  );
}

// ─── Live panel ────────────────────────────────────────────────────────────

type StreamStatus = 'idle' | 'connecting' | 'live' | 'complete' | 'error';

function LivePanel() {
  const [arcs, setArcs] = useState<ArcOption[]>([]);
  const [selectedArc, setSelectedArc] = useState<string>('');
  const [status, setStatus] = useState<StreamStatus>('idle');
  const [frame, setFrame] = useState<StreamFrame | null>(null);
  const [message, setMessage] = useState<string>('');
  const esRef = useRef<EventSource | null>(null);

  // Load arc list from manifest on mount
  useEffect(() => {
    fetch('/api/lab/manifest')
      .then((r) => r.json())
      .then((manifest: { arcs: ArcOption[] }) => {
        setArcs(manifest.arcs ?? []);
        if (manifest.arcs?.length) setSelectedArc(manifest.arcs[0].id);
      })
      .catch(() => { /* no-op — arcs stay empty */ });
  }, []);

  const stopStream = useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
  }, []);

  const startStream = useCallback(() => {
    stopStream();
    if (!selectedArc) return;

    setStatus('connecting');
    setFrame(null);
    setMessage('Connecting…');

    const es = new EventSource(`/api/analysis/stream/${encodeURIComponent(selectedArc)}`);
    esRef.current = es;

    es.onmessage = (e: MessageEvent) => {
      try {
        const f: StreamFrame = JSON.parse(e.data);
        setFrame(f);
        if (f.message) setMessage(f.message);
        if (f.frame_type === 'heartbeat') setStatus('live');
        if (f.frame_type === 'complete') {
          setStatus('complete');
          es.close();
          esRef.current = null;
        }
      } catch { /* malformed frame — ignore */ }
    };

    es.onerror = () => {
      setStatus('error');
      setMessage('Stream connection lost.');
      es.close();
      esRef.current = null;
    };
  }, [selectedArc, stopStream]);

  // Clean up on unmount
  useEffect(() => () => stopStream(), [stopStream]);

  const latestMetrics = frame?.metrics_history.at(-1) ?? null;
  const events = frame?.events ?? [];

  const statusDot: Record<StreamStatus, string> = {
    idle: 'bg-white/20',
    connecting: 'bg-yellow-400 animate-pulse',
    live: 'bg-green-400 animate-pulse',
    complete: 'bg-[#FFB000]',
    error: 'bg-red-500',
  };
  const statusLabel: Record<StreamStatus, string> = {
    idle: 'IDLE',
    connecting: 'CONNECTING',
    live: 'LIVE',
    complete: 'COMPLETE',
    error: 'ERROR',
  };

  return (
    <div className="flex flex-col gap-3 h-full overflow-y-auto px-1 py-1">

      {/* Controls row */}
      <div className="flex items-center gap-2 flex-wrap">
        <select
          value={selectedArc}
          onChange={(e) => setSelectedArc(e.target.value)}
          disabled={status === 'connecting' || status === 'live'}
          className="flex-1 min-w-0 bg-black border border-[#FFB000]/40 text-[#FFB000] font-mono text-[11px] px-2 py-1 rounded-sm focus:outline-none focus:border-[#FFB000] disabled:opacity-40"
        >
          {arcs.length === 0 && <option value="">Loading arcs…</option>}
          {arcs.map((a) => (
            <option key={a.id} value={a.id}>
              {a.label} {a.peak_f1 !== null ? `· peak F1 ${pct(a.peak_f1 ?? 0)}` : ''}
            </option>
          ))}
        </select>

        {status === 'live' || status === 'connecting' ? (
          <button
            type="button"
            onClick={stopStream}
            className="shrink-0 bg-red-900/60 border border-red-500/60 text-red-400 font-mono text-[11px] px-3 py-1 rounded-sm hover:bg-red-900/80 transition-colors"
          >
            ■ STOP
          </button>
        ) : (
          <button
            type="button"
            onClick={startStream}
            disabled={!selectedArc}
            className="shrink-0 bg-[#FFB000]/10 border border-[#FFB000]/50 text-[#FFB000] font-mono text-[11px] px-3 py-1 rounded-sm hover:bg-[#FFB000]/20 disabled:opacity-40 transition-colors"
          >
            ▶ STREAM
          </button>
        )}

        {/* Status badge */}
        <div className="flex items-center gap-1.5 shrink-0">
          <span className={`inline-block w-2 h-2 rounded-full ${statusDot[status]}`} />
          <span className="font-mono text-[10px] text-white/50">{statusLabel[status]}</span>
        </div>
      </div>

      {/* Message ticker */}
      {message && (
        <p className="font-mono text-[10px] text-white/40 truncate border-l-2 border-[#FFB000]/30 pl-2">
          {message}
        </p>
      )}

      {/* Metrics section */}
      {latestMetrics ? (
        <div className="flex flex-col gap-2 border border-white/10 rounded-sm p-2">
          <div className="flex items-center justify-between">
            <span className="font-mono text-[10px] text-white/30 uppercase tracking-widest">
              Metrics · iter {latestMetrics.iteration}
            </span>
            {latestMetrics.activated && (
              <span className="font-mono text-[9px] bg-green-900/50 text-green-400 border border-green-500/30 px-1.5 py-0.5 rounded-sm">
                ✓ ACTIVATED
              </span>
            )}
          </div>
          <MetricBar label="P" value={latestMetrics.precision} color="#60a5fa" />
          <MetricBar label="R" value={latestMetrics.recall} color="#a78bfa" />
          <MetricBar label="F1" value={latestMetrics.f1} color={f1Color(latestMetrics.f1)} />
          <div className="flex gap-3 text-[10px] font-mono text-white/30 mt-0.5">
            <span>GT: {latestMetrics.n_gt}</span>
            <span>Pred: {latestMetrics.n_pred}</span>
            <span>Matched: {latestMetrics.matched}</span>
            <span className="text-red-400/70">Halls: {latestMetrics.hallucinations}</span>
          </div>
        </div>
      ) : status === 'idle' ? (
        <div className="flex-1 flex items-center justify-center">
          <p className="font-mono text-[11px] text-white/30 text-center">
            Select an arc and press ▶ STREAM<br />to watch live results roll in.
          </p>
        </div>
      ) : (
        <div className="border border-white/10 rounded-sm p-2 animate-pulse">
          <div className="h-3 bg-white/10 rounded-sm w-3/4 mb-2" />
          <div className="h-3 bg-white/10 rounded-sm w-full mb-1" />
          <div className="h-3 bg-white/10 rounded-sm w-full mb-1" />
          <div className="h-3 bg-white/10 rounded-sm w-full" />
        </div>
      )}

      {/* F1 Trend sparkline */}
      {(frame?.metrics_history.length ?? 0) > 0 && (
        <div className="flex flex-col gap-1 border border-white/10 rounded-sm p-2">
          <span className="font-mono text-[10px] text-white/30 uppercase tracking-widest mb-1">F1 Trend</span>
          <F1Sparkline history={frame!.metrics_history} />
          <div className="flex justify-between text-[9px] font-mono text-white/20 mt-0.5">
            <span>iter 1</span>
            <span>iter {frame!.metrics_history.length}</span>
          </div>
        </div>
      )}

      {/* Detected events */}
      {events.length > 0 && (
        <div className="flex flex-col gap-2 border border-white/10 rounded-sm p-2">
          <div className="flex items-center justify-between">
            <span className="font-mono text-[10px] text-white/30 uppercase tracking-widest">
              Detected Events ({events.length})
            </span>
          </div>

          {/* Confidence timeline dot-plot */}
          <ConfidenceTimeline events={events} duration={0} />

          {/* Per-event rows */}
          <div className="flex flex-col gap-1 max-h-28 overflow-y-auto">
            {[...events].sort((a, b) => a.timestamp_sec - b.timestamp_sec).map((ev) => (
              <div key={ev.event_id} className="flex items-center gap-2 text-[10px] font-mono">
                <span className="bg-[#FFB000] text-black px-1 py-0.5 shrink-0 text-[9px]">
                  {fmtTime(ev.timestamp_sec)}
                </span>
                <span className="flex-1 truncate text-white/70">{ev.technique}</span>
                <div className="w-16 h-2 bg-white/10 rounded-sm overflow-hidden shrink-0">
                  <div
                    className="h-full rounded-sm transition-all duration-500"
                    style={{ width: `${Math.round(ev.confidence * 100)}%`, backgroundColor: f1Color(ev.confidence) }}
                  />
                </div>
                <span style={{ color: f1Color(ev.confidence) }} className="w-7 text-right shrink-0">
                  {ev.confidence_pct}
                </span>
              </div>
            ))}
          </div>

          {/* Technique frequency chart */}
          {events.length > 1 && (
            <div className="mt-1 pt-2 border-t border-white/5">
              <span className="font-mono text-[10px] text-white/30 uppercase tracking-widest block mb-1">
                Technique Frequency
              </span>
              <TechniqueChart events={events} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Main exported component ───────────────────────────────────────────────

interface AnalysisResultProps {
  result: TimestampEvent[];
  onTimestampClick: (time: number) => void;
}

type ResultTab = 'log' | 'live';

export const AnalysisResult: React.FC<AnalysisResultProps> = ({ result, onTimestampClick }) => {
  const [tab, setTab] = useState<ResultTab>('log');

  return (
    <div className="h-full flex flex-col bg-black text-[#FFB000]">
      {/* Header + tab bar */}
      <div className="shrink-0 px-2 pt-2">
        <h3 className="font-display text-2xl text-center pb-1">ANALYSIS LOG</h3>
        <div className="flex border-b border-[#FFB000]/20">
          {(['log', 'live'] as ResultTab[]).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTab(t)}
              className={[
                'flex-1 font-mono text-xs py-1 tracking-widest uppercase transition-colors',
                tab === t
                  ? 'text-[#FFB000] border-b-2 border-[#FFB000] -mb-px'
                  : 'text-white/30 hover:text-white/60',
              ].join(' ')}
            >
              {t === 'live' ? '● LIVE' : 'LOG'}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-hidden p-2">
        {tab === 'log' ? (
          result && result.length > 0 ? (
            <div className="h-full overflow-y-auto pr-1">
              <div className="flex flex-col gap-3 text-sm">
                {result.map((event, index) => (
                  <div
                    key={index}
                    className="text-left hover:bg-white/10 p-2 transition-colors select-text"
                  >
                    <p className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => onTimestampClick(event.timestamp)}
                        className="font-bold bg-[#FFB000] text-black px-2 py-0.5 text-xs"
                        title="Jump to timestamp"
                      >
                        {fmtTime(event.timestamp)}
                      </button>
                      <span className="font-bold uppercase">{event.title}</span>
                    </p>
                    <p className="mt-1 opacity-80">{event.description}</p>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="h-full flex items-center justify-center">
              <p className="text-center opacity-50 font-mono text-xs">
                Awaiting video analysis.<br />Press 'Analyse' to begin.
              </p>
            </div>
          )
        ) : (
          <LivePanel />
        )}
      </div>
    </div>
  );
};