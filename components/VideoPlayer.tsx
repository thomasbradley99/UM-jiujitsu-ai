import React, { forwardRef, useState, useRef, useCallback, useEffect } from 'react';
import { CoachingOverlay, DrawingInstruction } from './CoachingOverlay';
import { Loader } from './Loader';
import type { PersonaStatus } from '../App';

interface VideoPlayerProps {
  videoUrl: string | null;
  drawingInstructions: DrawingInstruction[];
  videoDimensions: { width: number, height: number };
  personaStatus: PersonaStatus;
  onActivateCoach: () => void;
  onDeactivateCoach: () => void;
  onQueryPersonaConfig: () => void;
  coachPosition: { x: number, y: number };
  setCoachPosition: (pos: { x: number, y: number }) => void;
  isMicMuted: boolean;
  onToggleMicrophone: () => void;
  personaWindowSize: { width: number, height: number };
  setPersonaWindowSize: (size: { width: number, height: number }) => void;
}

export const VideoPlayer = forwardRef<HTMLVideoElement, VideoPlayerProps>(({ videoUrl, drawingInstructions, videoDimensions, personaStatus, onActivateCoach, onDeactivateCoach, onQueryPersonaConfig, coachPosition, setCoachPosition, isMicMuted, onToggleMicrophone, personaWindowSize, setPersonaWindowSize }, ref) => {
  const [isDragging, setIsDragging] = useState(false);
  const [isResizing, setIsResizing] = useState(false);
  const [volume, setVolume] = useState(1.0);
  const dragOffset = useRef({ x: 0, y: 0 });
  const resizeOffset = useRef({ x: 0, y: 0 });
  const coachWindowRef = useRef<HTMLDivElement>(null);
  const personaVideoRef = useRef<HTMLVideoElement>(null);

  const onMouseDown = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (coachWindowRef.current) {
      setIsDragging(true);
      const rect = coachWindowRef.current.getBoundingClientRect();
      dragOffset.current = {
        x: e.clientX - rect.left,
        y: e.clientY - rect.top,
      };
      e.preventDefault();
    }
  }, []);

  const onMouseMove = useCallback((e: MouseEvent) => {
    if (isDragging) {
      setCoachPosition({
        x: e.clientX - dragOffset.current.x,
        y: e.clientY - dragOffset.current.y,
      });
    } else if (isResizing) {
      const newWidth = Math.max(120, e.clientX - resizeOffset.current.x);
      const newHeight = Math.max(90, e.clientY - resizeOffset.current.y);
      setPersonaWindowSize({
        width: newWidth,
        height: newHeight,
      });
    }
  }, [isDragging, isResizing, setCoachPosition, setPersonaWindowSize]);

  const onMouseUp = useCallback(() => {
    setIsDragging(false);
    setIsResizing(false);
  }, []);

  const onResizeMouseDown = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (coachWindowRef.current) {
      setIsResizing(true);
      const rect = coachWindowRef.current.getBoundingClientRect();
      resizeOffset.current = {
        x: e.clientX - rect.width,
        y: e.clientY - rect.height,
      };
      e.preventDefault();
      e.stopPropagation();
    }
  }, []);

  useEffect(() => {
    if (isDragging || isResizing) {
      window.addEventListener('mousemove', onMouseMove);
      window.addEventListener('mouseup', onMouseUp);
    } else {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    }
    return () => {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };
  }, [isDragging, isResizing, onMouseMove, onMouseUp]);

  // Handle volume changes
  const handleVolumeChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const newVolume = parseFloat(e.target.value);
    setVolume(newVolume);
    if (personaVideoRef.current) {
      personaVideoRef.current.volume = newVolume;
    }
  }, []);



  return (
    <div className="relative w-full aspect-video bg-[#2F2F2F] flex items-center justify-center border-t-2 border-l-2 border-[#F5F5DC] border-b-2 border-r-2 border-gray-500">
      {videoUrl ? (
        <video
          ref={ref}
          key={videoUrl}
          className="w-full h-full object-contain"
        >
          <source src={videoUrl} />
          Your browser does not support the video tag.
        </video>
      ) : (
         <div className="text-center text-[#C0C0C0]/50 p-8 font-display">
           <p className="text-4xl">PLEASE LOAD A VIDEO TAPE</p>
         </div>
      )}

      {videoUrl && <CoachingOverlay instructions={drawingInstructions} videoDimensions={videoDimensions} />}

      <div 
        ref={coachWindowRef}
        className="bg-[#C0C0C0] border-t-2 border-l-2 border-[#F5F5DC] border-b-2 border-r-2 border-gray-500 shadow-lg flex flex-col"
        style={{
          position: 'fixed',
          top: coachPosition.y,
          left: coachPosition.x,
          width: personaWindowSize.width,
          height: personaWindowSize.height + 40, // +40 for header and controls
          zIndex: 50,
        }}
      >
        <div 
          className="h-6 bg-[#355E3B] text-white font-display text-lg px-2 flex items-center cursor-move"
          onMouseDown={onMouseDown}
        >
          AI COACH
        </div>
        <div 
          className="bg-black overflow-hidden relative flex-1"
          style={{ height: personaWindowSize.height }}
        >
          <video 
              ref={personaVideoRef}
              id="anam-mount-point"
              className={`w-full h-full object-cover transition-opacity duration-300 ${personaStatus === 'ready' ? 'opacity-100' : 'opacity-0'}`}
              autoPlay
              playsInline
              muted={false}
              volume={volume}
          />
          {personaStatus !== 'ready' && (
              <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/50 text-white text-xs text-center p-1">
                  {personaStatus === 'inactive' && (
                      <button 
                          onClick={onActivateCoach}
                          className="bg-black/50 hover:bg-black/70 font-bold p-2 border border-white/50 transition-colors"
                      >
                          ACTIVATE
                      </button>
                  )}
                  {personaStatus === 'loading' && (
                      <>
                          <Loader />
                          <p className="mt-1 font-display">CONNECTING</p>
                      </>
                  )}
                  {personaStatus === 'error' && (
                      <p className="text-red-400 font-display">ERROR</p>
                  )}
              </div>
          )}
        </div>
        
        {/* Control buttons */}
        {personaStatus === 'ready' && (
          <div className="h-8 bg-[#C0C0C0] border-t border-gray-400 flex items-center justify-between px-2 gap-2">
            <div className="flex items-center gap-2">
              <button
                onClick={onToggleMicrophone}
                className={`text-xs px-2 py-1 border border-gray-500 ${
                  isMicMuted 
                    ? 'bg-red-400 text-white' 
                    : 'bg-green-400 text-white'
                }`}
                title={isMicMuted ? 'Click to unmute microphone' : 'Click to mute microphone'}
              >
                {isMicMuted ? '🔇' : '🎤'}
              </button>
              
              {/* Volume control */}
              <div className="flex items-center gap-1">
                <span className="text-xs">🔊</span>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.1"
                  value={volume}
                  onChange={handleVolumeChange}
                  className="w-16 h-1"
                  title="Adjust volume"
                />
              </div>
            </div>
            
            {/* Resize handle */}
            <div
              onMouseDown={onResizeMouseDown}
              className="w-4 h-4 bg-gray-400 cursor-nw-resize border border-gray-600 flex items-center justify-center"
              style={{
                background: 'linear-gradient(-45deg, transparent 0%, transparent 30%, #666 30%, #666 35%, transparent 35%, transparent 65%, #666 65%, #666 70%, transparent 70%)'
              }}
              title="Drag to resize window"
            />
          </div>
        )}
        
        {/* Deactivate button row */}
        {personaStatus === 'ready' && (
          <div className="h-6 bg-[#C0C0C0] border-t border-gray-400 flex items-center justify-center px-2 gap-2">
            <button 
              onClick={onDeactivateCoach}
              className="text-xs px-2 py-0.5 border border-gray-500 bg-white hover:bg-gray-100 text-black transition-colors"
              title="Deactivate Joe Rogan"
            >
              DEACTIVATE
            </button>
            <button 
              onClick={onQueryPersonaConfig}
              className="text-xs px-2 py-0.5 border border-gray-500 bg-white hover:bg-gray-100 text-black transition-colors"
              title="Query current persona configuration and system prompt"
            >
              QUERY
            </button>
          </div>
        )}
      </div>
    </div>
  );
});