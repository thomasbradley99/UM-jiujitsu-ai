import React from 'react';

export interface TimestampEvent {
  timestamp: number;
  title: string;
  description: string;
}

interface AnalysisResultProps {
  result: TimestampEvent[];
  onTimestampClick: (time: number) => void;
}

const formatTime = (seconds: number) => {
  const minutes = Math.floor(seconds / 60).toString().padStart(2, '0');
  const remainingSeconds = Math.floor(seconds % 60).toString().padStart(2, '0');
  return `${minutes}:${remainingSeconds}`;
};

export const AnalysisResult: React.FC<AnalysisResultProps> = ({ result, onTimestampClick }) => {
  if (!result || result.length === 0) {
    return (
      <div className="h-full flex flex-col p-2 bg-black text-[#FFB000]">
        <h3 className="font-display text-2xl text-center pb-2 border-b border-[#FFB000]/30">ANALYSIS LOG</h3>
        <div className="flex-grow flex items-center justify-center">
            <p className="text-center opacity-70">Awaiting video analysis. Press 'Analyse' to begin.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-black text-[#FFB000] p-2">
      <h3 className="font-display text-2xl text-center pb-2 border-b border-[#FFB000]/30">ANALYSIS LOG</h3>
      <div className="flex-grow overflow-y-auto mt-2 pr-2">
        <div className="flex flex-col gap-3 text-sm">
          {result.map((event, index) => (
            <div
              key={index}
              className="text-left hover:bg-white/10 focus:bg-white/20 outline-none p-2 transition-colors select-text"
            >
              <p className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => onTimestampClick(event.timestamp)}
                  className="font-bold bg-[#FFB000] text-black px-2 py-0.5 text-xs"
                  title="Jump to timestamp"
                >
                  {formatTime(event.timestamp)}
                </button>
                <span className="font-bold uppercase">{event.title}</span>
              </p>
              <p className="mt-1 opacity-80">{event.description}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};