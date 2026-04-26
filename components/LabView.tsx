import React, { useEffect, useState } from 'react';
import GameLibrary from './GameLibrary';
import ArcExplorer from './ArcExplorer';
import CrossEvalMatrix from './CrossEvalMatrix';
import MuBitResults from './MuBitResults';
import VisualizationDashboard from './VisualizationDashboard';
import { fetchManifest, triggerBuild, type Manifest } from '../services/labService';

type Tab = 'games' | 'arcs' | 'cross-eval' | 'visualization' | 'mubit';

const TABS: { id: Tab; label: string }[] = [
  { id: 'visualization', label: 'VISUALIZATION' },
  { id: 'mubit', label: 'MUBIT RESULTS' },
  { id: 'games', label: 'GAME LIBRARY' },
  { id: 'arcs', label: 'ARC EXPLORER' },
  { id: 'cross-eval', label: 'CROSS-EVAL MATRIX' },
];

const LabView: React.FC = () => {
  const [tab, setTab] = useState<Tab>('games');
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [building, setBuilding] = useState(false);
  const [buildMsg, setBuildMsg] = useState<string | null>(null);

  useEffect(() => {
    fetchManifest().then(setManifest).catch(() => null);
  }, []);

  const handleBuild = async () => {
    setBuilding(true);
    setBuildMsg(null);
    try {
      const res = await triggerBuild();
      setBuildMsg(res.ok ? '✓ Build complete' : `Build failed: ${res.output}`);
      if (res.ok) {
        setManifest(await fetchManifest());
      }
    } catch (e: any) {
      setBuildMsg(`Build error: ${e.message}`);
    } finally {
      setBuilding(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#0d1117] text-[#c9d1d9] font-mono">
      {/* Header */}
      <div className="border-b border-white/10 px-6 py-4">
        <div className="max-w-5xl mx-auto flex items-start justify-between gap-4">
          <div>
            <h1 className="text-[#FFB000] font-bold text-lg tracking-wider uppercase">
              BJJ Submission Detector — Research Lab
            </h1>
            {manifest && (
              <p className="text-white/30 text-[11px] mt-1">
                Built {new Date(manifest.built_at).toLocaleString()} ·{' '}
                {manifest.games.length} games · {manifest.arcs.length} arcs ·{' '}
                {manifest.cross_eval_games.length} cross-eval games
              </p>
            )}
          </div>
          <div className="flex flex-col items-end gap-1.5 shrink-0">
            <button
              type="button"
              onClick={handleBuild}
              disabled={building}
              className="px-3 py-1.5 text-[11px] font-mono bg-[#FFB000]/10 hover:bg-[#FFB000]/20 text-[#FFB000] border border-[#FFB000]/30 rounded transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {building ? '⏳ Building…' : '⟳ Rebuild Data'}
            </button>
            {buildMsg && (
              <span
                className={`text-[10px] font-mono ${
                  buildMsg.startsWith('✓') ? 'text-green-400' : 'text-red-400'
                }`}
              >
                {buildMsg}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Tab bar */}
      <div className="border-b border-white/10 px-6">
        <div className="max-w-5xl mx-auto flex gap-0">
          {TABS.map(({ id, label }) => (
            <button
              key={id}
              type="button"
              onClick={() => setTab(id)}
              className={`px-4 py-2.5 text-[11px] tracking-widest font-mono transition-colors border-b-2 -mb-px ${
                tab === id
                  ? 'text-[#FFB000] border-[#FFB000]'
                  : 'text-white/30 border-transparent hover:text-white/60'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="max-w-5xl mx-auto px-6 py-6">
        {tab === 'visualization' && <VisualizationDashboard />}
        {tab === 'mubit' && <MuBitResults />}
        {tab === 'games' && <GameLibrary />}
        {tab === 'arcs' && <ArcExplorer />}
        {tab === 'cross-eval' && <CrossEvalMatrix />}
      </div>
    </div>
  );
};

export default LabView;
