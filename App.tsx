import React, { useState, useCallback, useEffect, useRef } from 'react';
import { createClient, unsafe_createClientWithApiKey } from '@anam-ai/js-sdk';
import { VideoPlayer } from './components/VideoPlayer';
import { identifyFighters, analyseVideo, analyseVideoInChunks, getCoachingOverlay, type FighterProfile } from './services/geminiService';
import { logger } from './services/logger';
import { getSessionToken } from './services/anamService';
import { getDefaultPersona } from './services/personas';
import { DrawingInstruction } from './components/CoachingOverlay';
import { TimestampEvent, AnalysisResult } from './components/AnalysisResult';
import { ProVideoWindow } from './components/ProVideoWindow';
import { ProVideoControls } from './components/ProVideoControls';
import { BackgroundChanger } from './components/BackgroundChanger';
import { PersonaChanger } from './components/PersonaChanger';
import type { PersonaConfig } from './services/anamService';

export type PersonaStatus = 'inactive' | 'loading' | 'ready' | 'error';

const App: React.FC = () => {
  // Core state
  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<TimestampEvent[] | null>(null);
  const [fighterProfiles, setFighterProfiles] = useState<{ fighter1: FighterProfile; fighter2: FighterProfile } | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [isIdentifyingFighters, setIsIdentifyingFighters] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState({ currentTime: 0, duration: 0 });
  const [isPlaying, setIsPlaying] = useState(false);
  const [backgroundUrl, setBackgroundUrl] = useState<string | null>(null);

  // Coaching state
  const [isCoaching, setIsCoaching] = useState<boolean>(false);
  const [capturedFrame, setCapturedFrame] = useState<string | null>(null);
  const [coachingPrompt, setCoachingPrompt] = useState<string>('');
  const [drawingInstructions, setDrawingInstructions] = useState<DrawingInstruction[]>([]);
  const [videoDimensions, setVideoDimensions] = useState({ width: 0, height: 0 });
  const [coachPosition, setCoachPosition] = useState({ x: window.innerWidth - 170, y: 50 });
  
  // Anam Persona State
  const [anamPersona, setAnamPersona] = useState<any>(null);
  const [personaStatus, setPersonaStatus] = useState<PersonaStatus>('inactive');
  const [isMicMuted, setIsMicMuted] = useState<boolean>(true);
  const [isVideoMuted, setIsVideoMuted] = useState<boolean>(false);
  const [personaWindowSize, setPersonaWindowSize] = useState({ width: 160, height: 120 });
  const [selectedPersonaConfig, setSelectedPersonaConfig] = useState<PersonaConfig>(getDefaultPersona());

  const videoRef = useRef<HTMLVideoElement>(null);
  const anamPersonaRef = useRef<any>(null);

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      if (videoUrl) URL.revokeObjectURL(videoUrl);
      setVideoFile(file);
      const url = URL.createObjectURL(file);
      setVideoUrl(url);
      setAnalysis(null);
      setFighterProfiles(null);
      setError(null);
      setCapturedFrame(null);
      setDrawingInstructions([]);
      setCoachingPrompt('');
      setPersonaStatus('inactive');
      setAnamPersona(null);
      if (anamPersonaRef.current) {
        try {
          anamPersonaRef.current.stopStreaming().catch((error) => {
            console.warn('Failed to stop persona streaming:', error);
          });
        } catch (error) {
          console.warn('Failed to stop persona streaming:', error);
        }
        anamPersonaRef.current = null;
      }
    }
  };
  
  const handleBackgroundChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      if (backgroundUrl) URL.revokeObjectURL(backgroundUrl);
      const url = URL.createObjectURL(file);
      setBackgroundUrl(url);
    }
  };

  const handleImportAnalysisFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    try {
      const file = event.target.files?.[0];
      if (!file) return;
      const text = await file.text();
      const json = JSON.parse(text);
      // Accept either an array of events [{timestamp,title,description}] or
      // a richer schema where we can map start_seconds->timestamp and label->title
      const normalize = (item: any): TimestampEvent | null => {
        if (!item) return null;
        const timestamp = typeof item.timestamp === 'number' ? item.timestamp
          : typeof item.start_seconds === 'number' ? item.start_seconds
          : typeof item.time === 'number' ? item.time
          : null;
        const title = typeof item.title === 'string' ? item.title
          : typeof item.label === 'string' ? item.label
          : typeof item.event === 'string' ? item.event
          : typeof item.type === 'string' ? item.type
          : null;
        const description = typeof item.description === 'string' ? item.description
          : typeof item.summary === 'string' ? item.summary
          : title || '';
        if (timestamp == null || title == null) return null;
        return { timestamp, title, description };
      };
      const arr = Array.isArray(json) ? json
        : Array.isArray(json?.events) ? json.events
        : Array.isArray(json?.timeline_events) ? json.timeline_events
        : Array.isArray(json?.data) ? json.data
        : [];
      const events: TimestampEvent[] = arr.map(normalize).filter(Boolean) as TimestampEvent[];
      events.sort((a, b) => a.timestamp - b.timestamp);
      setAnalysis(events);
      setError(null);
    } catch (e) {
      console.error('Failed to import analysis file', e);
      setError('Failed to import analysis JSON. Ensure it is valid and try again.');
    } finally {
      // reset the input so same file can be chosen again if needed
      (event.target as HTMLInputElement).value = '';
    }
  };


  const fileToBase64 = (file: File): Promise<string> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.readAsDataURL(file);
      reader.onload = () => resolve((reader.result as string).split(',')[1]);
      reader.onerror = (error) => reject(error);
    });
  };

  const handleAnalyseClick = useCallback(async () => {
    if (!videoFile) return;
    
    // Start professional logging
    const runId = logger.startRun(videoFile.name, videoFile.size, videoFile.type);
    
    setIsLoading(true);
    setIsIdentifyingFighters(true);
    setError(null);
    setAnalysis(null);
    setFighterProfiles(null);
    setDrawingInstructions([]);

    try {
      const base64Video = await fileToBase64(videoFile);
      
      // Step 1: Identify fighters and create profiles
      const profiles = await identifyFighters(base64Video, videoFile.type);
      setFighterProfiles(profiles);
      setIsIdentifyingFighters(false);
      
      // Step 2: Analyze video with fighter context
      // Force single analysis for better results and speed
      const durationSec = Math.floor(videoRef.current?.duration || 0);
      const isLarge = (videoFile.size || 0) > 80 * 1024 * 1024; // >80MB
      const useChunks = false; // Force single analysis - much faster and better quality

      let result: TimestampEvent[];
      if (useChunks) {
        console.log('🧩 Using chunked analysis (30s windows)', { durationSec, sizeMB: Math.round(videoFile.size / (1024*1024)) });
        result = await analyseVideoInChunks(base64Video, videoFile.type, profiles, durationSec, 30, 14);
      } else {
        result = await analyseVideo(base64Video, videoFile.type, profiles);
      }
      setAnalysis(result);
      
      logger.finishRun('completed');
    } catch (err) {
      console.error('Analysis failed:', err);
      setError('Failed to analyse the video. The AI could not process this format or the response was invalid.');
      logger.finishRun('failed');
    } finally {
      setIsLoading(false);
      setIsIdentifyingFighters(false);
    }
  }, [videoFile]);
  
  const handleTimestampClick = (time: number) => {
    if (videoRef.current) {
      videoRef.current.currentTime = time;
      videoRef.current.play();
    }
  };

  const handleExportAnalysis = useCallback(() => {
    try {
      const data = analysis || [];
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      const base = videoFile?.name?.replace(/\.[^.]+$/, '') || 'analysis';
      a.href = url;
      a.download = `${base}-timeline.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error('Export failed', e);
      setError('Failed to export analysis JSON.');
    }
  }, [analysis, videoFile]);

  const handleCaptureFrame = async () => {
    if (!videoRef.current) return;
    const video = videoRef.current;
    video.pause();
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    const frameDataUrl = canvas.toDataURL('image/jpeg');
    setCapturedFrame(frameDataUrl);
    setDrawingInstructions([]);
    if (anamPersona) {
      try {
        anamPersona.interruptPersona();
      } catch (error) {
        console.warn('Failed to interrupt persona:', error);
      }
    }
  };

  const handleGetCoaching = async () => {
      if (!capturedFrame || !coachingPrompt) return;
      setIsCoaching(true);
      setError(null);
      setDrawingInstructions([]);
      try {
        const base64Image = capturedFrame.split(',')[1];
        const result = await getCoachingOverlay(base64Image, coachingPrompt);
        setDrawingInstructions(result);

        if (anamPersona && result.length > 0) {
            const notes = result.map(instr => instr.description).filter(Boolean).join(' ');
            if (notes) {
                try {
                    // Add current video timestamp context for Joe
                    const currentTime = videoRef.current?.currentTime || 0;
                    const timeContext = `At ${Math.floor(currentTime / 60)}:${String(Math.floor(currentTime % 60)).padStart(2, '0')} in the video: ${notes}`;
                    
                    console.log('🎯 SENDING COACHING CONTEXT TO JOE:');
                    console.log('   Timestamp:', `${Math.floor(currentTime / 60)}:${String(Math.floor(currentTime % 60)).padStart(2, '0')}`);
                    console.log('   Coaching Notes:', notes);
                    console.log('   Full Message:', timeContext);
                    
                    const startTime = Date.now();
                    await anamPersona.talk(timeContext);
                    const endTime = Date.now();
                    
                    console.log('✅ COACHING CONTEXT SENT TO JOE!');
                    console.log(`   Duration: ${endTime - startTime}ms`);
                } catch (error) {
                    console.error('❌ FAILED TO SEND COACHING NOTES TO JOE:', error);
                    console.log('   Error Details:', error.message);
                }
            } else {
                console.log('⚠️ NO COACHING NOTES TO SEND TO JOE (empty descriptions)');
            }
        } else {
            console.log('⚠️ CANNOT SEND COACHING TO JOE:');
            console.log('   Anam Persona Active:', !!anamPersona);
            console.log('   Coaching Results:', result.length);
        }
      } catch (err) {
        console.error('Coaching failed:', err);
        setError('Failed to get coaching feedback.');
      } finally {
        setIsCoaching(false);
      }
  };
  
  const handleActivateCoach = useCallback(async () => {
    // 🧪 DEBUG: Check state at activation time
    console.log('🚀 ACTIVATING JOE - Current State:', {
      analysisExists: !!analysis,
      analysisLength: analysis?.length || 0,
      personaStatus,
      selectedPersona: selectedPersonaConfig?.name
    });

    if (personaStatus !== 'inactive') return;
    setPersonaStatus('loading');
    
    try {
      console.log('Starting persona activation with:', selectedPersonaConfig.name);
      
      if (!process.env.ANAM_API_KEY) {
        throw new Error('ANAM_API_KEY environment variable is not set');
      }
      
      // Check if video element exists
      const videoElement = document.getElementById('anam-mount-point');
      if (!videoElement) {
        throw new Error('Video element with ID "anam-mount-point" not found');
      }
      
      // Use unsafe method directly as shown in Anam docs for development
      // For custom personas like Joe Rogan, use personaId; for built personas, use individual components
      
      // Build contextual system prompt with fight analysis
      let contextualSystemPrompt = selectedPersonaConfig.systemPrompt;
      
      // Add fighter profiles context if available
      if (fighterProfiles) {
        const fighterContext = `\n\nFIGHTER PROFILES:
${fighterProfiles.fighter1.name} (${fighterProfiles.fighter1.fightingStyle}):
- Experience: ${fighterProfiles.fighter1.experience}
- Strengths: ${fighterProfiles.fighter1.strengths.join(', ')}
- Notable Techniques: ${fighterProfiles.fighter1.notableTechniques.join(', ')}

${fighterProfiles.fighter2.name} (${fighterProfiles.fighter2.fightingStyle}):
- Experience: ${fighterProfiles.fighter2.experience}
- Strengths: ${fighterProfiles.fighter2.strengths.join(', ')}
- Notable Techniques: ${fighterProfiles.fighter2.notableTechniques.join(', ')}`;
        
        contextualSystemPrompt += fighterContext;
        console.log('👥 FIGHTER PROFILES ADDED TO CONTEXT');
      }
      
      // Add fight analysis context if available  
      if (analysis && analysis.length > 0) {
        const fightContext = analysis.map(event => 
          `${Math.floor(event.timestamp / 60)}:${String(Math.floor(event.timestamp % 60)).padStart(2, '0')} - ${event.title}: ${event.description}`
        ).join('\n');
        
        contextualSystemPrompt += `\n\nFIGHT ANALYSIS: You just watched this detailed match analysis:\n${fightContext}\n\nYou can reference these specific moments and the fighters' techniques in your commentary. Be enthusiastic about the technical exchanges you observed!`;
        
        console.log('📊 FIGHT ANALYSIS ADDED TO CONTEXT');
      }
      
      console.log('🎙️ FINAL PERSONA CONTEXT LENGTH:', contextualSystemPrompt.length, 'characters');
      console.groupCollapsed('📋 FULL SYSTEM PROMPT FOR JOE:');
      console.log(contextualSystemPrompt);
      console.groupEnd();
      
      // Summary of what Joe will receive
      console.log('📊 JOE ROGAN CONTEXT SUMMARY:');
      console.log('   Base Personality:', selectedPersonaConfig.systemPrompt.substring(0, 50) + '...');
      console.log('   Fighter Profiles:', fighterProfiles ? 'INCLUDED' : 'NOT INCLUDED');
      console.log('   Fight Analysis:', analysis ? `${analysis.length} events` : 'NOT INCLUDED');
      console.log('   Total Context Size:', contextualSystemPrompt.length, 'characters');
      
      let personaConfig;
      if (selectedPersonaConfig.personaId) {
        // Custom persona with personaId
        personaConfig = {
          personaId: selectedPersonaConfig.personaId,
          systemPrompt: contextualSystemPrompt
        };
        
        // For hybrid personas, add custom voice if specified
        if (selectedPersonaConfig.voiceId) {
          personaConfig.voiceId = selectedPersonaConfig.voiceId;
        }
      } else {
        // Built persona with individual components
        personaConfig = {
          name: selectedPersonaConfig.name,
          avatarId: selectedPersonaConfig.avatarId,
          voiceId: selectedPersonaConfig.voiceId,
          llmId: selectedPersonaConfig.llmId,
          systemPrompt: contextualSystemPrompt
        };
      }
      
      // 🔍 LOG EXACTLY WHAT WE'RE SENDING TO ANAM
      console.log('🚀 CREATING ANAM CLIENT WITH CONFIG:');
      console.log('   API Key:', process.env.ANAM_API_KEY ? `${process.env.ANAM_API_KEY.substring(0, 10)}...` : 'NOT SET');
      console.log('   Persona Config:', personaConfig);
      console.groupCollapsed('📋 FULL PERSONA CONFIG SENT TO ANAM:');
      console.log(JSON.stringify(personaConfig, null, 2));
      console.groupEnd();
      
      const anamClient = unsafe_createClientWithApiKey(
        process.env.ANAM_API_KEY,
        personaConfig
      );
      
      console.log('✅ ANAM CLIENT CREATED SUCCESSFULLY');
      console.log('   Client Type:', typeof anamClient);
      console.log('   Client Methods:', Object.getOwnPropertyNames(Object.getPrototypeOf(anamClient)));
      
      console.log('🎥 STREAMING TO VIDEO ELEMENT...');
      console.log('   Target Element ID: anam-mount-point');
      console.log('   Expected System Prompt Length:', contextualSystemPrompt.length);
      
      await anamClient.streamToVideoElement('anam-mount-point');
      
      console.log('✅ STREAMING STARTED SUCCESSFULLY');
      
      setAnamPersona(anamClient);
      // Attach transcript handlers if available, otherwise start local recognizer
      try {
        attachTranscriptHandlers(anamClient);
      } catch (e) {
        console.warn('attachTranscriptHandlers failed, starting local recognition fallback', e);
        startLocalRecognition();
      }
      anamPersonaRef.current = anamClient;
      setPersonaStatus('ready');
      
      // Initialize microphone as muted
      const audioState = anamClient.getInputAudioState();
      setIsMicMuted(audioState.isMuted);
      
      // Send fight context as initial talk command for immediate awareness
      if (analysis && analysis.length > 0 && fighterProfiles) {
        const contextMessage = `Hey Joe! I just analyzed a fight between ${fighterProfiles.fighter1.name} and ${fighterProfiles.fighter2.name}. Here are the key moments I found: ${analysis.slice(0, 3).map(event => `At ${Math.floor(event.timestamp / 60)}:${String(Math.floor(event.timestamp % 60)).padStart(2, '0')} - ${event.title}`).join(', ')}. What do you think about this match?`;
        
        console.log('🎙️ SENDING INITIAL CONTEXT TO JOE:', contextMessage);
        console.log('📊 CONTEXT DATA BEING SENT:');
        console.log('   Fighter 1:', fighterProfiles.fighter1.name, '-', fighterProfiles.fighter1.experience);
        console.log('   Fighter 2:', fighterProfiles.fighter2.name, '-', fighterProfiles.fighter2.experience);
        console.log('   Total Events:', analysis.length);
        console.log('   Sample Events:', analysis.slice(0, 3).map(e => `${e.timestamp}s: ${e.title}`));
        
        // Use talk() method to send context directly
        setTimeout(async () => {
          try {
            console.log('⏰ ATTEMPTING TO SEND CONTEXT (2 second delay)...');
            const startTime = Date.now();
            
            await anamClient.talk(contextMessage);
            
            const endTime = Date.now();
            console.log('✅ CONTEXT SUCCESSFULLY SENT TO JOE!');
            console.log(`   📈 Send Duration: ${endTime - startTime}ms`);
            console.log(`   📝 Message Length: ${contextMessage.length} characters`);
            console.log(`   🎯 Joe should now know about: ${fighterProfiles.fighter1.name} vs ${fighterProfiles.fighter2.name}`);
            
            // Log what Joe should now be aware of
            console.groupCollapsed('🧠 JOE\'S EXPECTED KNOWLEDGE:');
            console.log('Fighter Profiles:', fighterProfiles);
            console.log('Fight Events:', analysis);
            console.log('System Prompt Length:', contextualSystemPrompt.length);
            console.groupEnd();
            
          } catch (error) {
            console.error('❌ FAILED TO SEND CONTEXT TO JOE:', error);
            console.log('   Error Type:', error.constructor.name);
            console.log('   Error Message:', error.message);
          }
        }, 2000); // Wait 2 seconds for persona to fully initialize
      } else {
        console.warn('⚠️ NO CONTEXT TO SEND TO JOE:');
        console.log('   Analysis exists:', !!analysis);
        console.log('   Analysis length:', analysis?.length || 0);
        console.log('   Fighter profiles exist:', !!fighterProfiles);
        console.log('   💡 TIP: Run ANALYSE first, then ACTIVATE Joe!');
      }
      
    } catch (error) {
      console.error("Anam AI Persona failed:", error);
      setError(`AI Persona failed to load: ${error instanceof Error ? error.message : 'Unknown error'}`);
      setPersonaStatus('error');
    }
  }, [personaStatus, selectedPersonaConfig]);

  const handleDeactivateCoach = useCallback(async () => {
    console.log('🛑 DEACTIVATING JOE ROGAN...');
    
    try {
      if (anamPersona) {
        console.log('   Stopping streaming...');
        await anamPersona.stopStreaming();
        console.log('   ✅ Streaming stopped');
      }
      
      // Reset all persona state
      setAnamPersona(null);
      anamPersonaRef.current = null;
      setPersonaStatus('inactive');
      setIsMicMuted(false);
      
      console.log('✅ JOE ROGAN DEACTIVATED');
      console.log('   Ready to reactivate with fresh context!');
      
    } catch (error) {
      console.error('❌ Error deactivating Joe:', error);
      // Force reset anyway
      setAnamPersona(null);
      anamPersonaRef.current = null;
      setPersonaStatus('inactive');
      setIsMicMuted(false);
    }
  }, [anamPersona]);

  const handleToggleMicrophone = useCallback(() => {
    if (!anamPersona) return;
    
    try {
      let audioState;
      if (isMicMuted) {
        audioState = anamPersona.unmuteInputAudio();
        console.log('Microphone unmuted');
      } else {
        audioState = anamPersona.muteInputAudio();
        console.log('Microphone muted');
      }
      setIsMicMuted(audioState.isMuted);
    } catch (error) {
      console.warn('Failed to toggle microphone:', error);
    }
  }, [anamPersona, isMicMuted]);

  // Manual context refresh for Joe Rogan
  const handleRefreshJoeContext = useCallback(async () => {
    if (!anamPersona || !analysis || !fighterProfiles) {
      console.warn('🚫 CANNOT REFRESH JOE CONTEXT:');
      console.log('   Anam Persona:', !!anamPersona);
      console.log('   Analysis:', !!analysis);
      console.log('   Fighter Profiles:', !!fighterProfiles);
      return;
    }
    
    try {
      const contextRefresh = `Let me refresh your memory about this fight. We have ${fighterProfiles.fighter1.name} (${fighterProfiles.fighter1.experience} ${fighterProfiles.fighter1.fightingStyle}) versus ${fighterProfiles.fighter2.name} (${fighterProfiles.fighter2.experience} ${fighterProfiles.fighter2.fightingStyle}). The key moments were: ${analysis.map(event => `${Math.floor(event.timestamp / 60)}:${String(Math.floor(event.timestamp % 60)).padStart(2, '0')} - ${event.title}`).join(', ')}. Got all that?`;
      
      console.log('🔄 MANUAL CONTEXT REFRESH FOR JOE:');
      console.log('   Message Length:', contextRefresh.length, 'characters');
      console.log('   Events Count:', analysis.length);
      console.log('   Full Message:', contextRefresh);
      
      const startTime = Date.now();
      await anamPersona.talk(contextRefresh);
      const endTime = Date.now();
      
      console.log('✅ MANUAL CONTEXT REFRESH SUCCESSFUL!');
      console.log(`   Duration: ${endTime - startTime}ms`);
      console.log('   Joe should now have refreshed knowledge of all fight events');
    } catch (error) {
      console.error('❌ MANUAL CONTEXT REFRESH FAILED:', error);
      console.log('   Error Details:', {
        name: error.constructor.name,
        message: error.message,
        stack: error.stack
      });
    }
  }, [anamPersona, analysis, fighterProfiles]);

  // Query current persona configuration from Anam SDK
  const handleQueryPersonaConfig = useCallback(async () => {
    if (!anamPersona) {
      console.warn('🚫 CANNOT QUERY PERSONA CONFIG:');
      console.log('   Anam Persona Active:', !!anamPersona);
      return;
    }

    try {
      console.log('🔍 QUERYING CURRENT PERSONA CONFIGURATION...');
      
      // Try to get the current persona config from the SDK
      if (typeof anamPersona.getPersonaConfig === 'function') {
        const currentConfig = await anamPersona.getPersonaConfig();
        console.log('📋 CURRENT PERSONA CONFIG FROM SDK:');
        console.log('   Config Object:', currentConfig);
        console.groupCollapsed('📝 FULL PERSONA CONFIG:');
        console.log(JSON.stringify(currentConfig, null, 2));
        console.groupEnd();
        
        if (currentConfig.systemPrompt) {
          console.log('🎙️ CURRENT SYSTEM PROMPT:');
          console.log('   Length:', currentConfig.systemPrompt.length, 'characters');
          console.groupCollapsed('📋 FULL SYSTEM PROMPT:');
          console.log(currentConfig.systemPrompt);
          console.groupEnd();
        }
      } else {
        console.warn('⚠️ getPersonaConfig method not available on this SDK version');
      }

      // Try to get active session info
      if (typeof anamPersona.getActiveSessionId === 'function') {
        const sessionId = await anamPersona.getActiveSessionId();
        console.log('🔗 ACTIVE SESSION ID:', sessionId);
      }

      // Log what we know locally
      console.log('🏠 LOCAL PERSONA INFO:');
      console.log('   Selected Persona:', selectedPersonaConfig?.name);
      console.log('   Persona ID:', selectedPersonaConfig?.personaId);
      console.log('   Status:', personaStatus);
      
    } catch (error) {
      console.error('❌ FAILED TO QUERY PERSONA CONFIG:', error);
      console.log('   Error Details:', {
        name: error.constructor.name,
        message: error.message
      });
    }
  }, [anamPersona, selectedPersonaConfig, personaStatus]);

  // --- Voice command support (Anam transcripts if available, else Web Speech API fallback) ---
  const lastCommandAtRef = useRef<number>(0);
  const recognizerRef = useRef<any>(null);

  const stopLocalRecognition = useCallback(() => {
    try {
      if (recognizerRef.current) {
        recognizerRef.current.onresult = null;
        recognizerRef.current.onend = null;
        recognizerRef.current.onerror = null;
        recognizerRef.current.stop();
        recognizerRef.current = null;
      }
    } catch (e) {
      console.warn('Failed to stop local SpeechRecognition', e);
    }
  }, []);

  const startLocalRecognition = useCallback(() => {
    const SpeechRecognition = (window as any).webkitSpeechRecognition || (window as any).SpeechRecognition;
    if (!SpeechRecognition) {
      console.warn('Web Speech API not available in this browser');
      return null;
    }
    try {
      const r = new SpeechRecognition();
      r.lang = 'en-US';
      r.interimResults = false;
      r.maxAlternatives = 1;
      r.onresult = (e: any) => {
        const text = e.results?.[0]?.[0]?.transcript;
        if (text) parseAndExecuteVoiceCommand(text);
      };
      r.onerror = (err: any) => console.warn('SpeechRecognition error', err);
      r.onend = () => {
        // auto-restart for continuous listening
        try {
          if (recognizerRef.current) recognizerRef.current.start();
        } catch (e) {
          // ignore
        }
      };
      r.start();
      recognizerRef.current = r;
      return r;
    } catch (err) {
      console.warn('Failed to start SpeechRecognition', err);
      return null;
    }
  }, []);

  const speakAck = useCallback(async (text: string) => {
    // Use Anam persona TTS exclusively when available. Do not fallback to
    // browser speechSynthesis to avoid a second voice speaking.
    try {
      if (anamPersona && typeof anamPersona.talk === 'function') {
        // Cancel any in-progress browser TTS before persona speaks
        try { window.speechSynthesis?.cancel(); } catch (e) { /* ignore */ }
        await anamPersona.talk(text);
      } else {
        // If no anam persona is active, do not speak to avoid unexpected voices.
        console.log('speakAck skipped: no anam persona available');
      }
    } catch (e) {
      console.warn('anamPersona.talk failed', e);
    }
  }, [anamPersona]);

  const parseAndExecuteVoiceCommand = useCallback(async (transcript: string) => {
    const now = Date.now();
    if (now - (lastCommandAtRef.current || 0) < 700) return; // simple cooldown
    lastCommandAtRef.current = now;

    const text = (transcript || '').toLowerCase().trim();
    if (!text) return;
    console.log('VOICE CMD:', text);

    // helper to make persona acknowledge before action
    const personaAcknowledgeAndRun = async (ackText: string, action: () => void) => {
      const hadRecognizer = !!recognizerRef.current;
      try {
        // stop local recognizer so persona speech doesn't retrigger
        if (hadRecognizer) stopLocalRecognition();
        // interrupt persona's current turn if supported
        try {
          if (anamPersona) {
            if (typeof anamPersona.interrupt === 'function') await anamPersona.interrupt();
            else if (typeof anamPersona.interruptPersona === 'function') await anamPersona.interruptPersona();
          }
        } catch (e) { /* ignore */ }
        await speakAck(ackText);
      } catch (e) {
        console.warn('persona acknowledgement failed', e);
      } finally {
        try { action(); } catch (e) { console.warn('action failed', e); }
        // restart recognizer if it was running
        if (hadRecognizer) startLocalRecognition();
      }
    };

    // pause / stop
    if (/\b(pause|stop)\b/.test(text)) {
      await personaAcknowledgeAndRun('Pausing the video now.', () => { videoRef.current?.pause(); });
      return;
    }
    // play / resume
    if (/\b(play|resume)\b/.test(text)) {
      await personaAcknowledgeAndRun('Resuming playback.', () => { videoRef.current?.play(); });
      return;
    }
    // rewind N seconds (or default 5)
    if (/\b(rewind|go back|back up)\b/.test(text)) {
      const m = text.match(/(\d+)\s*(seconds?|secs?|s)/);
      const secs = m ? parseInt(m[1], 10) : 5;
  await personaAcknowledgeAndRun(`Rewinding ${secs} seconds.`, () => { if (videoRef.current) videoRef.current.currentTime = Math.max(0, videoRef.current.currentTime - secs); });
      return;
    }
    // fast forward N seconds (or default 5)
    if (/\b(fast forward|skip forward|skip|forward)\b/.test(text)) {
      const m = text.match(/(\d+)\s*(seconds?|secs?|s)/);
      const secs = m ? parseInt(m[1], 10) : 5;
  await personaAcknowledgeAndRun(`Skipping forward ${secs} seconds.`, () => { if (videoRef.current) videoRef.current.currentTime = Math.min(videoRef.current.duration || Infinity, videoRef.current.currentTime + secs); });
      return;
    }
    // seek to minute:second or seconds
    const seekMatch = text.match(/(?:go to|skip to|seek to)\s+(?:(\d+)\s*minutes?)?\s*(?:(\d+)\s*seconds?)?/);
    if (seekMatch && (seekMatch[1] || seekMatch[2])) {
      const mins = parseInt(seekMatch[1] || '0', 10) || 0;
      const secs = parseInt(seekMatch[2] || '0', 10) || 0;
      const t = mins * 60 + secs;
  await personaAcknowledgeAndRun(`Skipping to ${Math.floor(t/60)}:${String(t%60).padStart(2,'0')}`, () => { if (videoRef.current) videoRef.current.currentTime = Math.min(videoRef.current.duration || 0, t); });
      return;
    }
    // mute / unmute
    if (/\b(mute)\b/.test(text)) {
      await personaAcknowledgeAndRun('Muting video.', () => { if (videoRef.current) videoRef.current.muted = true; setIsVideoMuted(true); });
      return;
    }
    if (/\b(unmute|volume up)\b/.test(text)) {
      await personaAcknowledgeAndRun('Unmuting video.', () => { if (videoRef.current) videoRef.current.muted = false; setIsVideoMuted(false); });
      return;
    }

    // fallback: let persona respond conversationally
    try {
      await personaAcknowledgeAndRun("Sorry, I didn't understand that — can you repeat?", () => {});
    } catch (e) {
      console.warn('speakAck failed', e);
    }
  }, [speakAck]);

  const attachTranscriptHandlers = useCallback((client: any) => {
    if (!client) return;
    // Try common event names - attach safely
    const handler = (payload: any) => {
      const text = typeof payload === 'string' ? payload : (payload?.text || payload?.transcript || payload?.content?.text);
      const isFinal = payload?.isFinal ?? true;
      if (text && isFinal) parseAndExecuteVoiceCommand(text);
    };
    try {
      if (typeof client.on === 'function') {
        ['transcript', 'inputTranscription', 'utterance', 'message', 'transcription'].forEach((ev) => {
          try { client.on(ev, handler); } catch (e) { /* ignore */ }
        });
        return;
      }
      if (typeof (client as any).onTranscript === 'function') {
        try { (client as any).onTranscript(handler); return; } catch (e) {}
      }
    } catch (e) {
      console.warn('Failed to attach transcript handlers', e);
    }
    // Last resort: start local SpeechRecognition
    startLocalRecognition();
  }, [parseAndExecuteVoiceCommand, startLocalRecognition]);

  const handlePersonaChange = useCallback(async (newPersonaConfig: PersonaConfig) => {
    console.log('Changing persona to:', newPersonaConfig.name, 'Current status:', personaStatus);
    
    // If a persona is currently active, stop it first
    if (personaStatus === 'ready' && anamPersonaRef.current) {
      console.log('Stopping current persona...');
      setPersonaStatus('loading');
      
      try {
        await anamPersonaRef.current.stopStreaming();
        setAnamPersona(null);
        anamPersonaRef.current = null;
        console.log('Current persona stopped successfully');
      } catch (error) {
        console.warn('Failed to stop current persona:', error);
      }
    }
    
    // Update to new persona configuration
      setSelectedPersonaConfig(newPersonaConfig);
    console.log('Persona configuration updated to:', newPersonaConfig.name);
    
    // If we were in ready state, automatically activate the new persona
    if (personaStatus === 'ready' || personaStatus === 'loading') {
      console.log('Auto-activating new persona...');
      setPersonaStatus('inactive'); // Reset status first
      
      // Small delay to ensure cleanup is complete
      setTimeout(() => {
        handleActivateCoach();
      }, 100);
    }
  }, [personaStatus, handleActivateCoach]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const handleTimeUpdate = () => {
      setProgress({
        currentTime: video.currentTime,
        duration: video.duration || 0,
      });
    };
    const handleLoadedMetadata = () => {
      setProgress({
        currentTime: video.currentTime,
        duration: video.duration,
      });
    };
    const handlePlay = () => setIsPlaying(true);
    const handlePause = () => setIsPlaying(false);

    video.addEventListener('timeupdate', handleTimeUpdate);
    video.addEventListener('loadedmetadata', handleLoadedMetadata);
    video.addEventListener('play', handlePlay);
    video.addEventListener('pause', handlePause);
    
    const resizeObserver = new ResizeObserver(() => {
      setVideoDimensions({
          width: video.clientWidth,
          height: video.clientHeight,
      });
    });
    resizeObserver.observe(video);

    return () => {
      video.removeEventListener('timeupdate', handleTimeUpdate);
      video.removeEventListener('loadedmetadata', handleLoadedMetadata);
      video.removeEventListener('play', handlePlay);
      video.removeEventListener('pause', handlePause);
      resizeObserver.disconnect();
    };
  }, [videoUrl]);

  useEffect(() => {
    return () => {
      if (anamPersonaRef.current) {
        try {
          anamPersonaRef.current.stopStreaming().catch((error) => {
            console.warn('Failed to stop Anam persona streaming:', error);
          });
        } catch (error) {
          console.warn('Failed to stop Anam persona streaming:', error);
        }
      }
    };
  }, []);

  useEffect(() => {
      const videoElement = videoRef.current;
      const handlePlay = async () => {
          setDrawingInstructions([]);
          if (anamPersona) {
            try {
              await anamPersona.interrupt();
            } catch (error) {
              console.warn('Failed to interrupt persona:', error);
            }
          }
      };
      if (videoElement) {
          videoElement.addEventListener('play', handlePlay);
      }
      return () => {
          if (videoElement) {
              videoElement.removeEventListener('play', handlePlay);
          }
      };
  }, [videoUrl, anamPersona]);

  const handlePlayPause = () => {
    if (!videoRef.current) return;
    if (isPlaying) {
      videoRef.current.pause();
    } else {
      videoRef.current.play();
    }
  };

  const handleRewind = () => {
    if (videoRef.current) {
      videoRef.current.currentTime = Math.max(0, videoRef.current.currentTime - 5);
    }
  };
  
  const handleFastForward = () => {
    if (videoRef.current) {
      videoRef.current.playbackRate = videoRef.current.playbackRate === 2 ? 1 : 2;
    }
  };

  const handleToggleVideoMute = () => {
    setIsVideoMuted(prev => {
      const newMuted = !prev;
      if (videoRef.current) {
        videoRef.current.muted = newMuted;
      }
      return newMuted;
    });
  };


  return (
    <div 
        className="min-h-screen w-full bg-cover bg-center"
        style={{
            backgroundImage: backgroundUrl ? `url(${backgroundUrl})` : 'none',
        }}
    >
      <BackgroundChanger onBackgroundChange={handleBackgroundChange} />
      <PersonaChanger 
        currentPersona={selectedPersonaConfig}
        onPersonaChange={handlePersonaChange}
        personaStatus={personaStatus}
      />
      <div className="min-h-screen flex items-start justify-center p-4">
        {/* Left Panel - Analysis Log */}
        <div className="w-1/3 flex flex-col">
          <div className="h-[580px]">
            <AnalysisResult result={analysis || []} onTimestampClick={handleTimestampClick} />
          </div>
        </div>

        {/* Right Panel - Video Player */}
        <div className="flex-1 flex items-start justify-center">
        <ProVideoWindow>
          <VideoPlayer 
            ref={videoRef}
            videoUrl={videoUrl} 
            drawingInstructions={drawingInstructions}
            videoDimensions={videoDimensions}
            personaStatus={personaStatus}
            onActivateCoach={handleActivateCoach}
                onDeactivateCoach={handleDeactivateCoach}
                onQueryPersonaConfig={handleQueryPersonaConfig}
            coachPosition={coachPosition}
            setCoachPosition={setCoachPosition}
            isMicMuted={isMicMuted}
            onToggleMicrophone={handleToggleMicrophone}
            personaWindowSize={personaWindowSize}
            setPersonaWindowSize={setPersonaWindowSize}
          />
          <ProVideoControls
            videoFile={videoFile}
            onFileChange={handleFileChange}
            onImportAnalysisFile={handleImportAnalysisFile}
            videoLoaded={!!videoUrl}
            isLoading={isLoading || isCoaching}
            onAnalyse={handleAnalyseClick}
            onCaptureFrame={handleCaptureFrame}
            onGetCoaching={handleGetCoaching}
            onExportAnalysis={handleExportAnalysis}
            capturedFrame={capturedFrame}
            coachingPrompt={coachingPrompt}
            setCoachingPrompt={setCoachingPrompt}
            analysis={analysis}
            drawingInstructions={drawingInstructions}
            onTimestampClick={handleTimestampClick}
            onSeekToTime={handleTimestampClick}
            error={error}
            progress={progress}
            isPlaying={isPlaying}
            onPlayPause={handlePlayPause}
            onRewind={handleRewind}
            onFastForward={handleFastForward}
            playbackRate={videoRef.current?.playbackRate ?? 1}
                isVideoMuted={isVideoMuted}
                onToggleVideoMute={handleToggleVideoMute}
          />
        </ProVideoWindow>
        </div>
      </div>
    </div>
  );
};

export default App;