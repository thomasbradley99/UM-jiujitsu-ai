import React from 'react';
import { TimestampEvent, AnalysisResult } from './AnalysisResult';
import { DrawingInstruction } from './CoachingOverlay';
import { CoachingNotes } from './CoachingNotes';
import { Loader } from './Loader';

interface ProVideoControlsProps {
  videoFile: File | null;
  onFileChange: (event: React.ChangeEvent<HTMLInputElement>) => void;
  onImportAnalysisFile: (event: React.ChangeEvent<HTMLInputElement>) => void;
  videoLoaded: boolean;
  isLoading: boolean;
  onAnalyse: () => void;
  onCaptureFrame: () => void;
  onGetCoaching: () => void;
  capturedFrame: string | null;
  coachingPrompt: string;
  setCoachingPrompt: (value: string) => void;
  analysis: TimestampEvent[] | null;
  onExportAnalysis: () => void;
  drawingInstructions: DrawingInstruction[];
  onTimestampClick: (time: number) => void;
  error: string | null;
  progress: { currentTime: number; duration: number };
  isPlaying: boolean;
  onPlayPause: () => void;
  onRewind: () => void;
  onFastForward: () => void;
  playbackRate: number;
  isVideoMuted: boolean;
  onToggleVideoMute: () => void;
  onSeekToTime: (time: number) => void;
}

const formatTime = (seconds: number) => {
  if (isNaN(seconds) || seconds === 0) return '00:00';
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = Math.floor(seconds % 60);
  return `${minutes.toString().padStart(2, '0')}:${remainingSeconds.toString().padStart(2, '0')}`;
};

const ControlButton = ({ children, onClick, disabled, active, isPrimary }: { children: React.ReactNode, onClick?: () => void, disabled?: boolean, active?: boolean, isPrimary?: boolean }) => (
  <button 
    onClick={onClick} 
    disabled={disabled}
    className={`font-display text-xl px-4 py-2 border-t-2 border-l-2 border-[#F5F5DC] border-b-2 border-r-2 border-gray-500 transition-all duration-100 ease-in-out disabled:opacity-50 disabled:cursor-not-allowed active:border-t-2 active:border-l-2 active:border-gray-500 active:border-b-2 active:border-r-2 active:border-[#F5F5DC] ${
        isPrimary ? 'bg-[#CC3333] text-white' : 'bg-[#C0C0C0] text-black'
    } ${active ? 'bg-gray-400' : ''}`}
  >
    {children}
  </button>
);

const IndeterminateProgress = () => (
  <div className="w-full bg-black h-4 overflow-hidden border-2 border-gray-500 p-0.5">
    <div 
      className="bg-[#355E3B] h-full"
      style={{
        width: '100%',
        backgroundImage: 'linear-gradient(90deg, #355E3B 25%, #84a287 50%, #355E3B 75%)',
        backgroundSize: '200% 100%',
        animation: 'progress-animation 1.5s linear infinite',
      }}
    ></div>
    <style>{`
      @keyframes progress-animation {
        0% { background-position: 200% 0; }
        100% { background-position: -200% 0; }
      }
    `}</style>
  </div>
);


export const ProVideoControls: React.FC<ProVideoControlsProps> = (props) => {
  const { videoFile, onFileChange, onImportAnalysisFile, videoLoaded, isLoading, onAnalyse, onCaptureFrame, onGetCoaching, capturedFrame, coachingPrompt, setCoachingPrompt, analysis, onExportAnalysis, drawingInstructions, onTimestampClick, error, progress, isPlaying, onPlayPause, onRewind, onFastForward, playbackRate, isVideoMuted, onToggleVideoMute, onSeekToTime } = props;

  const progressPercent = progress.duration > 0 ? (progress.currentTime / progress.duration) * 100 : 0;

  // Handle timeline clicking for scrubbing
  const handleTimelineClick = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!videoLoaded || progress.duration === 0) return;
    
    const rect = event.currentTarget.getBoundingClientRect();
    const clickX = event.clientX - rect.left;
    const clickPercent = clickX / rect.width;
    const seekTime = clickPercent * progress.duration;
    
    onSeekToTime(Math.max(0, Math.min(progress.duration, seekTime)));
  };

  return (
    <div className="bg-[#C0C0C0] p-3 border-t-2 border-black/20 mt-1">
      {/* Top Info & Progress Bar */}
      <div className="mb-3">
        <div className="flex justify-between items-center text-black text-lg font-display mb-1 px-1">
          <p className="truncate pr-4">{videoFile ? `TAPE: ${videoFile.name}`: 'NO TAPE LOADED'}</p>
          <p>{formatTime(progress.currentTime)} / {formatTime(progress.duration)}</p>
        </div>
        <div 
          className="w-full bg-black h-4 border-t-2 border-l-2 border-gray-500 border-b-2 border-r-2 border-[#F5F5DC] cursor-pointer relative group"
          onClick={handleTimelineClick}
          title="Click to jump to time"
        >
          <div className="bg-[#355E3B] h-full transition-all" style={{ width: `${progressPercent}%` }}></div>
          
          {/* Event markers */}
          {analysis && analysis.map((event, index) => {
            const eventPercent = progress.duration > 0 ? (event.timestamp / progress.duration) * 100 : 0;
            return (
              <div
                key={index}
                className="absolute top-0 w-0.5 h-full bg-yellow-400 opacity-70 hover:opacity-100 cursor-pointer"
                style={{ left: `${eventPercent}%` }}
                title={`${formatTime(event.timestamp)}: ${event.title}`}
                onClick={(e) => {
                  e.stopPropagation();
                  onTimestampClick(event.timestamp);
                }}
              />
            );
          })}
          
          {/* Hover indicator */}
          <div className="absolute inset-0 opacity-0 group-hover:opacity-20 bg-white pointer-events-none transition-opacity"></div>
        </div>
      </div>

      {/* Main Controls */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <ControlButton onClick={onRewind} disabled={!videoLoaded}>{'<<'}</ControlButton>
          <button 
              onClick={onPlayPause} 
              disabled={!videoLoaded}
              className="font-display text-4xl w-16 h-14 bg-[#C0C0C0] text-black border-t-2 border-l-2 border-[#F5F5DC] border-b-2 border-r-2 border-gray-500 transition-all disabled:opacity-50 disabled:cursor-not-allowed active:border-t-2 active:border-l-2 active:border-gray-500 active:border-b-2 active:border-r-2 active:border-[#F5F5DC]"
            >
              {isPlaying ? 'II' : '▶'}
          </button>
          <ControlButton onClick={onFastForward} disabled={!videoLoaded} active={playbackRate > 1}>{'>>'}</ControlButton>
          <ControlButton onClick={onToggleVideoMute} disabled={!videoLoaded} active={isVideoMuted}>
            {isVideoMuted ? 'MUTE' : 'VOL'}
          </ControlButton>
        </div>
        
        <div className="flex items-center gap-2">
            <label htmlFor="video-upload" className="font-display text-xl px-4 py-2 border-t-2 border-l-2 border-[#F5F5DC] border-b-2 border-r-2 border-gray-500 bg-[#C0C0C0] text-black cursor-pointer">
              LOAD
            </label>
            <input id="video-upload" type="file" className="hidden" accept="video/*" onChange={onFileChange} />
            <label htmlFor="events-upload" className="font-display text-xl px-4 py-2 border-t-2 border-l-2 border-[#F5F5DC] border-b-2 border-r-2 border-gray-500 bg-[#C0C0C0] text-black cursor-pointer">
              IMPORT
            </label>
            <input id="events-upload" type="file" className="hidden" accept="application/json,.json" onChange={onImportAnalysisFile} />
            <ControlButton onClick={onCaptureFrame} disabled={!videoLoaded || isLoading}>CAPTURE</ControlButton>
            <ControlButton onClick={onAnalyse} disabled={!videoLoaded || isLoading} isPrimary>ANALYSE</ControlButton>
            <ControlButton onClick={onExportAnalysis} disabled={!analysis || analysis.length === 0}>EXPORT</ControlButton>
        </div>
      </div>
      
      {isLoading && (
        <div className="mt-4 space-y-2">
            <p className="text-center text-black font-display text-2xl">AI IS PROCESSING YOUR REQUEST...</p>
            <IndeterminateProgress />
        </div>
      )}

      {error && (
        <div className="mt-3 p-2 border-2 border-red-600 bg-red-200 text-red-900 text-sm">
          <strong>ERROR:</strong> {error}
        </div>
      )}

      {/* Analysis & Coaching Section */}
      {!isLoading && (
        <div className="mt-4 min-h-[200px] pt-3 border-t border-black/20">
          {capturedFrame && (
            <div className="flex flex-col gap-2 mb-4">
              <img src={capturedFrame} alt="Captured frame" className="w-full border-t-2 border-l-2 border-gray-500 border-b-2 border-r-2 border-[#F5F5DC]" />
              <textarea
                  value={coachingPrompt}
                  onChange={(e) => setCoachingPrompt(e.target.value)}
                  placeholder="Ask the AI coach for advice..."
                  className="w-full p-2 bg-[#F5F5DC] border-t-2 border-l-2 border-gray-500 border-b-2 border-r-2 border-[#F5F5DC] focus:outline-none focus:ring-2 focus:ring-[#355E3B]"
                  rows={2}
                  disabled={isLoading}
                />
              <button onClick={onGetCoaching} disabled={!coachingPrompt || isLoading} className="w-full p-2 bg-black text-white font-display text-xl transition-colors disabled:bg-gray-400">
                GET FEEDBACK
              </button>
              {drawingInstructions.length > 0 && <CoachingNotes instructions={drawingInstructions} />}
            </div>
          )}
          
          <div className="bg-[#C0C0C0] p-2 border-t-2 border-l-2 border-gray-500 border-b-2 border-r-2 border-[#F5F5DC]">
            <h3 className="font-display text-2xl text-black mb-2">SYSTEM STATUS</h3>
            <div className="text-sm space-y-1.5 text-black bg-[#F5F5DC] p-2">
              <p>{videoLoaded ? `> TAPE LOADED: READY` : '> STATUS: Awaiting video tape.'}</p>
              <p>{analysis ? `> ANALYSIS: Complete (${analysis.length} events found).` : '> ANALYSIS: Idle.'}</p>
              <p>{capturedFrame ? '> COACHING: Frame captured.' : '> COACHING: Ready.'}</p>
              <p>{drawingInstructions.length > 0 ? '> OVERLAY: Active.' : '> OVERLAY: Inactive.'}</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
