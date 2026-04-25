/*
 * IMPORTANT: API Key Configuration
 * --------------------------------
 * This service requires a Gemini API key to function.
 * 1. Create a file named `.env` in the root directory of this project.
 * 2. Add the following line to the `.env` file:
 *
 *    API_KEY="YOUR_GEMINI_API_KEY"
 *
 * 3. Replace "YOUR_GEMINI_API_KEY" with your actual Gemini API key.
 *
 * The `process.env.API_KEY` below will then be automatically populated.
 */

import { GoogleGenAI, Type } from "@google/genai";
import { TimestampEvent } from "../components/AnalysisResult";
import { DrawingInstruction } from "../components/CoachingOverlay";
import { logger } from "./logger";

export interface FighterProfile {
  name: string;
  fightingStyle: string;
  experience: string;
  strengths: string[];
  weaknesses: string[];
  notableTechniques: string[];
  physicalAttributes: string;
}

// Prefer Vite client env (VITE_*) for browser builds; fall back to server env
const VITE_API_KEY = (import.meta as any)?.env?.VITE_GEMINI_API_KEY || (import.meta as any)?.env?.VITE_API_KEY;
const SERVER_API_KEY = process.env.API_KEY;
const API_KEY = VITE_API_KEY || SERVER_API_KEY;

if (!API_KEY) {
  throw new Error("Gemini API key not set (VITE_GEMINI_API_KEY / VITE_API_KEY or API_KEY)");
}

const ai = new GoogleGenAI({ apiKey: API_KEY });

const timestampResponseSchema = {
  type: Type.ARRAY,
  items: {
    type: Type.OBJECT,
    properties: {
      timestamp: { type: Type.NUMBER, description: 'The event time in seconds.' },
      title: { type: Type.STRING, description: 'A short title for the event.' },
      description: { type: Type.STRING, description: 'A one-sentence summary.' },
    },
    required: ["timestamp", "title", "description"],
  },
};

const fighterProfileSchema = {
  type: Type.OBJECT,
  properties: {
    fighter1: {
      type: Type.OBJECT,
      properties: {
        name: { type: Type.STRING, description: "Fighter's name or identifier if unknown" },
        fightingStyle: { type: Type.STRING, description: "Primary martial art or fighting style" },
        experience: { type: Type.STRING, description: "Apparent skill level (beginner, intermediate, advanced, expert)" },
        strengths: { type: Type.ARRAY, items: { type: Type.STRING }, description: "Notable strengths observed" },
        weaknesses: { type: Type.ARRAY, items: { type: Type.STRING }, description: "Areas for improvement" },
        notableTechniques: { type: Type.ARRAY, items: { type: Type.STRING }, description: "Techniques frequently used or executed well" },
        physicalAttributes: { type: Type.STRING, description: "Physical characteristics affecting their style" }
      },
      required: ["name", "fightingStyle", "experience", "strengths", "weaknesses", "notableTechniques", "physicalAttributes"]
    },
    fighter2: {
      type: Type.OBJECT,
      properties: {
        name: { type: Type.STRING, description: "Fighter's name or identifier if unknown" },
        fightingStyle: { type: Type.STRING, description: "Primary martial art or fighting style" },
        experience: { type: Type.STRING, description: "Apparent skill level (beginner, intermediate, advanced, expert)" },
        strengths: { type: Type.ARRAY, items: { type: Type.STRING }, description: "Notable strengths observed" },
        weaknesses: { type: Type.ARRAY, items: { type: Type.STRING }, description: "Areas for improvement" },
        notableTechniques: { type: Type.ARRAY, items: { type: Type.STRING }, description: "Techniques frequently used or executed well" },
        physicalAttributes: { type: Type.STRING, description: "Physical characteristics affecting their style" }
      },
      required: ["name", "fightingStyle", "experience", "strengths", "weaknesses", "notableTechniques", "physicalAttributes"]
    }
  },
  required: ["fighter1", "fighter2"]
};

const coachingResponseSchema = {
  type: Type.ARRAY,
  items: {
    type: Type.OBJECT,
    properties: {
      type: { type: Type.STRING, enum: ['arrow', 'circle', 'text'], description: "The type of shape to draw." },
      color: { type: Type.STRING, description: "A hex color code for the shape, e.g., '#FF5733'." },
      description: { type: Type.STRING, description: "A concise, one-sentence explanation of what this drawing is highlighting. This will be read aloud." },
      start: { type: Type.OBJECT, properties: { x: { type: Type.NUMBER }, y: { type: Type.NUMBER } }, description: "Normalized start coordinates (0-1) for an arrow." },
      end: { type: Type.OBJECT, properties: { x: { type: Type.NUMBER }, y: { type: Type.NUMBER } }, description: "Normalized end coordinates (0-1) for an arrow." },
      center: { type: Type.OBJECT, properties: { x: { type: Type.NUMBER }, y: { type: Type.NUMBER } }, description: "Normalized center coordinates (0-1) for a circle." },
      radius: { type: Type.NUMBER, description: "Normalized radius (0-1) for a circle, relative to video width." },
      position: { type: Type.OBJECT, properties: { x: { type: Type.NUMBER }, y: { type: Type.NUMBER } }, description: "Normalized position (0-1) for text." },
      content: { type: Type.STRING, description: "The text content to display." },
    },
     required: ["type", "color", "description"],
  },
};

// NEW: Step 1 - Identify fighters and create profiles
export async function identifyFighters(base64Video: string, mimeType: string): Promise<{ fighter1: FighterProfile; fighter2: FighterProfile }> {
  const prompt = `Analyze this martial arts/combat sports video and create detailed profiles for both fighters. Watch the entire video and observe:

1. Fighting styles, techniques used, and skill levels
2. Physical attributes that affect their fighting approach
3. Strengths and weaknesses demonstrated
4. Notable techniques or signature moves
5. Experience level based on technique execution and ring awareness

Provide comprehensive profiles for both fighters that will help with detailed technical analysis. If names are unknown, use descriptive identifiers like "Fighter in Blue Gi" or "Taller Fighter".`;

  logger.startStep('fighterIdentification');
  
  try {
    const response = await ai.models.generateContent({
      model: 'gemini-2.5-flash',
      contents: { parts: [ { text: prompt }, { inlineData: { data: base64Video, mimeType: mimeType } } ] },
      config: {
        responseMimeType: "application/json",
        responseSchema: fighterProfileSchema,
      }
    });
    
    const result = JSON.parse(response.text.trim());
    logger.completeStep('fighterIdentification', result, true);
    return result;
  } catch (error) {
    console.error("Error in identifyFighters:", error);
    logger.completeStep('fighterIdentification', null, false, error instanceof Error ? error.message : 'Unknown error');
    throw new Error("The Gemini API call for fighter identification failed or returned an unexpected format.");
  }
}

// MODIFIED: Step 2 - Analyze video with fighter context
export async function analyseVideo(base64Video: string, mimeType: string, fighterProfiles: { fighter1: FighterProfile; fighter2: FighterProfile }): Promise<TimestampEvent[]> {
  const fighterContext = `
FIGHTER PROFILES:
${fighterProfiles.fighter1.name} (${fighterProfiles.fighter1.fightingStyle}):
- Experience: ${fighterProfiles.fighter1.experience}
- Strengths: ${fighterProfiles.fighter1.strengths.join(', ')}
- Notable Techniques: ${fighterProfiles.fighter1.notableTechniques.join(', ')}

${fighterProfiles.fighter2.name} (${fighterProfiles.fighter2.fightingStyle}):
- Experience: ${fighterProfiles.fighter2.experience}  
- Strengths: ${fighterProfiles.fighter2.strengths.join(', ')}
- Notable Techniques: ${fighterProfiles.fighter2.notableTechniques.join(', ')}`;

  const enhancedPrompt = `${fighterContext}

Analyze this sports video with the fighter profiles above in mind. Identify key moments, techniques, and strategic plays. Focus on:
- Technical exchanges between these specific fighters
- How each fighter's known strengths/weaknesses play out
- Moments where fighter profiles help explain what's happening
- Strategic decisions based on their fighting styles

For each event, provide a precise timestamp in seconds, a short punchy title, and a one-sentence description in the style of a technical sports commentator who knows these fighters well.`;

  logger.startStep('videoAnalysis');

  try {
    const response = await ai.models.generateContent({
      model: 'gemini-2.5-flash',
      contents: { parts: [ { text: enhancedPrompt }, { inlineData: { data: base64Video, mimeType: mimeType } } ] },
      config: {
        responseMimeType: "application/json",
        responseSchema: timestampResponseSchema,
      }
    });
    
    const result = JSON.parse(response.text.trim());
    logger.completeStep('videoAnalysis', result, true);
    return result;
  } catch (error) {
    console.error("Error in analyseVideo:", error);
    logger.completeStep('videoAnalysis', null, false, error instanceof Error ? error.message : 'Unknown error');
    throw new Error("The Gemini API call failed or returned an unexpected format.");
  }
}

// NEW: Optional chunked analysis helper - analyzes the video in N-second windows and aggregates
export async function analyseVideoInChunks(
  base64Video: string,
  mimeType: string,
  fighterProfiles: { fighter1: FighterProfile; fighter2: FighterProfile },
  durationSeconds: number,
  segmentSeconds: number = 30,
  maxSegments: number = 12
): Promise<TimestampEvent[]> {
  const safeDuration = Math.max(0, Math.floor(durationSeconds || 0));
  const windowSize = Math.max(10, Math.floor(segmentSeconds));
  const totalSegments = Math.min(maxSegments, Math.max(1, Math.ceil(safeDuration / windowSize)));

  const fighterContext = `
FIGHTER PROFILES:
${fighterProfiles.fighter1.name} (${fighterProfiles.fighter1.fightingStyle}):
- Experience: ${fighterProfiles.fighter1.experience}
- Strengths: ${fighterProfiles.fighter1.strengths.join(', ')}
- Notable Techniques: ${fighterProfiles.fighter1.notableTechniques.join(', ')}

${fighterProfiles.fighter2.name} (${fighterProfiles.fighter2.fightingStyle}):
- Experience: ${fighterProfiles.fighter2.experience}  
- Strengths: ${fighterProfiles.fighter2.strengths.join(', ')}
- Notable Techniques: ${fighterProfiles.fighter2.notableTechniques.join(', ')}`;

  logger.startStep('videoAnalysis');

  const aggregated: TimestampEvent[] = [];

  for (let i = 0; i < totalSegments; i += 1) {
    const start = i * windowSize;
    const end = Math.min(safeDuration, start + windowSize);
    const segmentPrompt = `${fighterContext}

Analyze ONLY the segment of this video between ${start} and ${end} seconds (inclusive). Identify at most 3 key events in this window.
Return a JSON array with objects { timestamp, title, description } using ABSOLUTE timestamps in seconds from the start of the full video.

In description, append concise coaching notes in this exact format: " F1: <advice for ${fighterProfiles.fighter1.name}> F2: <advice for ${fighterProfiles.fighter2.name}>".`;

    try {
      const response = await ai.models.generateContent({
        model: 'gemini-2.5-flash',
        contents: { parts: [ { text: segmentPrompt }, { inlineData: { data: base64Video, mimeType } } ] },
        config: {
          responseMimeType: 'application/json',
          responseSchema: timestampResponseSchema,
        }
      });

      const segmentEvents: TimestampEvent[] = JSON.parse(response.text.trim() || '[]');

      // Basic dedupe by rounded timestamp + title
      for (const ev of segmentEvents) {
        const exists = aggregated.some(e => Math.round(e.timestamp) === Math.round(ev.timestamp) && e.title === ev.title);
        if (!exists) aggregated.push(ev);
      }
    } catch (error) {
      console.error(`Error analysing segment ${i + 1}/${totalSegments} (${start}-${end}s):`, error);
      // Continue with best-effort aggregation
    }
  }

  // Sort by timestamp to produce a coherent timeline
  aggregated.sort((a, b) => a.timestamp - b.timestamp);
  logger.completeStep('videoAnalysis', aggregated, true);
  return aggregated;
}
export async function getCoachingOverlay(base64Image: string, prompt: string): Promise<DrawingInstruction[]> {
    const fullPrompt = `You are an expert sports coaching assistant. Your goal is to provide clear, actionable, and encouraging feedback. Analyse the user's pose/action in the provided image. Generate a JSON array of drawing instructions to overlay on the image, highlighting key areas for improvement.
    
    For each instruction, you MUST provide a 'description' explaining its purpose. This description will be read aloud to the user.

    Instructions must follow this JSON schema. All coordinates (x, y) and radius must be normalized between 0.0 and 1.0, where {x:0, y:0} is the top-left corner. Be precise with coordinates. Place text annotations in areas that do not obstruct the user's view of the action.

    Example: [{"type": "arrow", "color": "#FF0000", "start": {"x": 0.5, "y": 0.5}, "end": {"x": 1.0, "y": 1.0}, "description": "This arrow shows the ideal follow-through path for your arm."}]
    
    User's request: "${prompt}"`;

    logger.startStep('frameCoaching', { prompt });

    try {
        const imagePart = { inlineData: { data: base64Image, mimeType: 'image/jpeg' } };
        const textPart = { text: fullPrompt };
        
        const response = await ai.models.generateContent({
            model: 'gemini-2.5-flash',
            contents: { parts: [textPart, imagePart] },
            config: {
                responseMimeType: "application/json",
                responseSchema: coachingResponseSchema,
            }
        });

        const result = JSON.parse(response.text.trim());
        logger.completeStep('frameCoaching', result, true);
        return result;

    } catch (error) {
        console.error("Error in getCoachingOverlay:", error);
        logger.completeStep('frameCoaching', null, false, error instanceof Error ? error.message : 'Unknown error');
        throw new Error("The Gemini API call for coaching overlay failed.");
    }
}