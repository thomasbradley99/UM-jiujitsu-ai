// Browser-compatible logger - console-based logging for development
import type { FighterProfile } from './geminiService';
import type { TimestampEvent } from '../components/AnalysisResult';
import type { DrawingInstruction } from '../components/CoachingOverlay';

export interface AnalysisRun {
  runId: string;
  timestamp: string;
  videoFileName: string;
  videoFileSize: number;
  videoMimeType: string;
  steps: {
    fighterIdentification?: {
      startTime: string;
      endTime: string;
      duration: number;
      result: { fighter1: FighterProfile; fighter2: FighterProfile } | null;
      success: boolean;
      error?: string;
    };
    videoAnalysis?: {
      startTime: string;
      endTime: string;
      duration: number;
      result: TimestampEvent[] | null;
      success: boolean;
      error?: string;
    };
    frameCoaching?: {
      startTime: string;
      endTime: string;
      duration: number;
      result: DrawingInstruction[] | null;
      success: boolean;
      error?: string;
      prompt?: string;
    };
  };
  status: 'running' | 'completed' | 'failed';
  totalDuration?: number;
}

class Logger {
  private currentRun: AnalysisRun | null = null;
  private stepStartTimes: Map<string, number> = new Map();

  // Start a new analysis run
  startRun(videoFileName: string, videoFileSize: number, videoMimeType: string): string {
    const runId = `run_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    
    this.currentRun = {
      runId,
      timestamp: new Date().toISOString(),
      videoFileName,
      videoFileSize,
      videoMimeType,
      steps: {},
      status: 'running'
    };

    console.log(`🚀 Starting Analysis Run: ${runId}`);
    console.log(`📹 Video: ${videoFileName} (${(videoFileSize / 1024 / 1024).toFixed(2)}MB)`);
    
    return runId;
  }

  // Start a processing step
  startStep(stepName: 'fighterIdentification' | 'videoAnalysis' | 'frameCoaching', metadata?: any) {
    if (!this.currentRun) return;
    
    const startTime = Date.now();
    this.stepStartTimes.set(stepName, startTime);
    
    const stepLabels = {
      fighterIdentification: '👥 Identifying Fighters',
      videoAnalysis: '📊 Analyzing Video',
      frameCoaching: '🎯 Generating Coaching'
    };
    
    console.log(`${stepLabels[stepName]}...`);
    if (metadata) {
      console.log(`   Metadata:`, metadata);
    }
  }

  // Complete a processing step
  completeStep(
    stepName: 'fighterIdentification' | 'videoAnalysis' | 'frameCoaching',
    result: any,
    success: boolean,
    error?: string
  ) {
    if (!this.currentRun) return;
    
    const startTime = this.stepStartTimes.get(stepName);
    const endTime = Date.now();
    const duration = startTime ? endTime - startTime : 0;
    
    this.currentRun.steps[stepName] = {
      startTime: startTime ? new Date(startTime).toISOString() : new Date().toISOString(),
      endTime: new Date(endTime).toISOString(),
      duration,
      result: success ? result : null,
      success,
      error
    };

    const stepLabels = {
      fighterIdentification: '👥 Fighter Identification',
      videoAnalysis: '📊 Video Analysis', 
      frameCoaching: '🎯 Frame Coaching'
    };
    
    if (success) {
      console.log(`✅ ${stepLabels[stepName]} completed (${duration}ms)`);
      if (stepName === 'fighterIdentification' && result) {
        console.log(`   Fighter 1: ${result.fighter1?.name || 'Unknown'}`);
        console.log(`   Fighter 2: ${result.fighter2?.name || 'Unknown'}`);
      } else if (stepName === 'videoAnalysis' && result) {
        console.log(`   Events found: ${result.length}`);
      } else if (stepName === 'frameCoaching' && result) {
        console.log(`   Instructions: ${result.length}`);
      }
    } else {
      console.error(`❌ ${stepLabels[stepName]} failed (${duration}ms): ${error}`);
    }
    
    this.stepStartTimes.delete(stepName);
  }

  // Finish the current run
  finishRun(status: 'completed' | 'failed') {
    if (!this.currentRun) return;
    
    this.currentRun.status = status;
    this.currentRun.totalDuration = Date.now() - new Date(this.currentRun.timestamp).getTime();
    
    if (status === 'completed') {
      console.log(`🎉 Analysis Run Completed: ${this.currentRun.runId}`);
      console.log(`   Total Duration: ${this.currentRun.totalDuration}ms`);
    } else {
      console.error(`💥 Analysis Run Failed: ${this.currentRun.runId}`);
    }
    
    // Save run data to file (async, but don't wait)
    this.saveRunToFile().catch(error => {
      console.error('Failed to save run file:', error);
    });
    
    // Log full run data for debugging
    console.groupCollapsed(`📋 Full Run Data: ${this.currentRun.runId}`);
    console.log(JSON.stringify(this.currentRun, null, 2));
    console.groupEnd();
    
    this.currentRun = null;
    this.stepStartTimes.clear();
  }

  // Save run data using File System Access API (Chrome) or fallback to download
  private async saveRunToFile() {
    if (!this.currentRun) return;
    
    const jsonData = JSON.stringify(this.currentRun, null, 2);
    const filename = `${this.currentRun.runId}.json`;
    
    try {
      // Try modern File System Access API first (Chrome/Edge)
      if ('showSaveFilePicker' in window) {
        const fileHandle = await (window as any).showSaveFilePicker({
          suggestedName: filename,
          startIn: 'downloads',
          types: [{
            description: 'Analysis Run Data',
            accept: { 'application/json': ['.json'] }
          }]
        });
        
        const writable = await fileHandle.createWritable();
        await writable.write(jsonData);
        await writable.close();
        
        console.log(`📁 Run data saved to chosen location: ${filename}`);
        return;
      }
    } catch (error) {
      if (error.name !== 'AbortError') {
        console.warn('File System Access API failed, falling back to download:', error);
      }
    }
    
    // Fallback: Traditional download with better UX
    try {
      const blob = new Blob([jsonData], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      
      // Create download link with better attributes
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      link.style.display = 'none';
      
      // Add to DOM, click, and remove
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      
      // Clean up blob URL
      setTimeout(() => URL.revokeObjectURL(url), 100);
      
      console.log(`📁 Run data downloaded: ${filename}`);
      console.log(`💡 TIP: Move this file to your runs/ folder for organization`);
    } catch (error) {
      console.error('Failed to save run data:', error);
    }
  }

  // Get current run info
  getCurrentRun(): AnalysisRun | null {
    return this.currentRun;
  }
}

// Export singleton instance
export const logger = new Logger();