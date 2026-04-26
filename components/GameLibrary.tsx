import React, { useEffect, useState } from 'react';
import {
  fetchGames,
  formatTime,
  type Game,
  type Submission,
} from '../services/labService';

const TECHNIQUE_LABELS: Record<string, string> = {
  armbar: 'Armbar',
  rnc: 'RNC',
  triangle: 'Triangle',
  arm_triangle: 'Arm Triangle',
  americana: 'Americana',
  kimura: 'Kimura',
  guillotine: 'Guillotine',
  heel_hook: 'Heel Hook',
  smother: 'Smother',
  choke: 'Choke',
};

const badge = 'inline-block px-2 py-0.5 rounded text-[11px] font-mono bg-[#FFB000]/10 text-[#FFB000] border border-[#FFB000]/30 mr-1';

function SubmissionRow({ sub }: { sub: Submission }) {
  return (
    <div className="flex items-start gap-3 py-2 border-b border-white/5 last:border-0">
      <span className="shrink-0 font-mono text-xs bg-[#FFB000] text-black px-2 py-0.5 rounded">
        {formatTime(sub.timestamp)}
      </span>
      <div className="min-w-0">
        <span className={badge}>{TECHNIQUE_LABELS[sub.technique] ?? sub.technique}</span>
        <span className="text-white/60 text-xs">
          {sub.submitter} → {sub.submittee}
        </span>
        {sub.notes && (
          <p className="text-white/40 text-[11px] mt-0.5 font-mono">{sub.notes}</p>
        )}
      </div>
    </div>
  );
}

function GameCard({ game }: { game: Game }) {
  const [open, setOpen] = useState(false);
  const videoSrc = game.video_url
    ? game.video_url.replace(/^\/public\//, '/website/public/')
    : null;

  return (
    <div className="bg-black/60 border border-white/10 rounded-lg overflow-hidden">
      {/* Header */}
      <button
        type="button"
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-white/5 transition-colors text-left"
        onClick={() => setOpen((v) => !v)}
      >
        <div>
          <h3 className="font-mono text-sm font-bold text-[#FFB000] uppercase tracking-wider">
            {game.id}
          </h3>
          <p className="text-white/50 text-xs mt-0.5 font-mono">
            {game.duration_sec}s · {game.submissions.length} submissions ·{' '}
            {Object.keys(game.fighters).length} fighters
          </p>
        </div>
        <span className="text-white/30 text-lg font-mono">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="px-4 pb-4 border-t border-white/5">
          {/* Description */}
          {game.description && (
            <p className="text-white/60 text-xs font-mono mt-3 mb-3 leading-relaxed">
              {game.description}
            </p>
          )}

          {/* Fighters */}
          <div className="flex flex-wrap gap-2 mb-4">
            {Object.entries(game.fighters).map(([key, f]) => (
              <div key={key} className="flex items-center gap-1.5 text-xs font-mono bg-white/5 rounded px-2 py-1">
                <span className="text-[#FFB000] font-bold">{key}</span>
                <span className="text-white/40">·</span>
                <span className="text-white/60">{f.visual}</span>
                {f.role && (
                  <>
                    <span className="text-white/40">·</span>
                    <span className="text-white/40">{f.role}</span>
                  </>
                )}
              </div>
            ))}
          </div>

          {/* Video */}
          {videoSrc && (
            <div className="bg-black rounded overflow-hidden mb-4 max-w-sm">
              <video
                src={videoSrc}
                controls
                preload="metadata"
                className="w-full block"
              />
            </div>
          )}

          {/* Submissions timeline */}
          <div>
            <h4 className="text-white/30 font-mono text-[10px] uppercase tracking-widest mb-2">
              Ground Truth Submissions
            </h4>
            {game.submissions.map((sub, i) => (
              <SubmissionRow key={i} sub={sub} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

const GameLibrary: React.FC = () => {
  const [games, setGames] = useState<Game[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchGames()
      .then(setGames)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading)
    return (
      <p className="text-white/40 font-mono text-sm text-center mt-10 animate-pulse">
        Loading game library…
      </p>
    );
  if (error)
    return (
      <p className="text-red-400 font-mono text-sm text-center mt-10">
        Error: {error}
      </p>
    );
  if (games.length === 0)
    return (
      <p className="text-white/30 font-mono text-sm text-center mt-10 italic">
        No games found. Run <code className="bg-white/10 px-1 rounded">python website/build.py</code> first.
      </p>
    );

  return (
    <div className="flex flex-col gap-3">
      {games.map((g) => (
        <GameCard key={g.id} game={g} />
      ))}
    </div>
  );
};

export default GameLibrary;
