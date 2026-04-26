import React, { useEffect, useState } from 'react';
import {
  fetchCrossEval,
  formatPct,
  f1Color,
  type CrossEvalRow,
  type CrossEvalCell,
} from '../services/labService';

function CellTooltip({ cell }: { cell: CrossEvalCell }) {
  return (
    <div className="absolute z-20 bottom-full left-1/2 -translate-x-1/2 mb-2 w-52 bg-[#1a1a1a] border border-white/20 rounded-lg p-3 shadow-xl pointer-events-none">
      <p className="font-mono text-[10px] text-white/40 mb-2 truncate">{cell.prompt_version_id}</p>
      <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs font-mono">
        {[
          ['F1', formatPct(cell.f1)],
          ['Prec', formatPct(cell.precision)],
          ['Recall', formatPct(cell.recall)],
          ['TechAcc', formatPct(cell.technique_acc)],
          ['SubAcc', formatPct(cell.submitter_acc)],
          ['Matched', `${cell.matched}/${cell.n_gt}`],
          ['Halls', String(cell.hallucinations)],
        ].map(([label, val]) => (
          <React.Fragment key={label}>
            <span className="text-white/40">{label}</span>
            <span className="text-white/80">{val}</span>
          </React.Fragment>
        ))}
      </div>
    </div>
  );
}

function MatrixCell({ cell }: { cell: CrossEvalCell }) {
  const [hovered, setHovered] = useState(false);
  const bgOpacity = cell.f1 >= 0.8 ? 'bg-green-500/20' : cell.f1 >= 0.5 ? 'bg-yellow-500/20' : 'bg-red-500/20';

  return (
    <td
      className="relative text-center p-0"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div className={`mx-1 my-1 rounded flex items-center justify-center h-10 cursor-default ${bgOpacity}`}>
        <span className={`font-mono text-xs font-bold ${f1Color(cell.f1)}`}>
          {formatPct(cell.f1)}
        </span>
      </div>
      {hovered && <CellTooltip cell={cell} />}
    </td>
  );
}

function CrossEvalTable({ rows }: { rows: CrossEvalRow[] }) {
  // Collect all unique prompt labels (columns) in order from first row
  const firstRow = rows[0];
  if (!firstRow) return null;
  const cols = firstRow.cells.map((c) => c.label);

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs font-mono min-w-[400px]">
        <thead>
          <tr className="border-b border-white/10">
            <th className="text-left text-white/30 uppercase tracking-wider text-[10px] pb-2 pr-4 pl-1">
              Game
            </th>
            {cols.map((c) => (
              <th
                key={c}
                className="text-center text-white/30 uppercase tracking-wider text-[10px] pb-2 px-2"
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.game} className="border-b border-white/5 last:border-0">
              <td className="py-1 pr-4 pl-1 text-white/60 font-bold">{row.game}</td>
              {row.cells.map((cell) => (
                <MatrixCell key={cell.label} cell={cell} />
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const CrossEvalMatrix: React.FC = () => {
  const [rows, setRows] = useState<CrossEvalRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchCrossEval()
      .then(setRows)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading)
    return (
      <p className="text-white/40 font-mono text-sm text-center mt-10 animate-pulse">
        Loading cross-eval…
      </p>
    );
  if (error)
    return (
      <p className="text-red-400 font-mono text-sm text-center mt-10">
        Error: {error}
      </p>
    );

  return (
    <div>
      <p className="text-white/40 font-mono text-xs mb-4 leading-relaxed">
        Each cell shows F1 for a given prompt × game combination. Hover a cell for full
        metrics. Green ≥ 80%, yellow ≥ 50%, red &lt; 50%.
      </p>
      {rows.length === 0 ? (
        <p className="text-white/30 font-mono text-sm text-center mt-6 italic">
          No cross-eval data yet.
        </p>
      ) : (
        <div className="bg-black/60 border border-white/10 rounded-lg p-4">
          <CrossEvalTable rows={rows} />
        </div>
      )}
    </div>
  );
};

export default CrossEvalMatrix;
