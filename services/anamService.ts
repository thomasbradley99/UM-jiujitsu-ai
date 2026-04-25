// Anam SDK service for session token management and persona configuration
// This service handles secure communication with Anam API

export interface PersonaConfig {
  id: string;
  name: string;
  personaId?: string; // For custom personas like Joe Rogan
  avatarId?: string;
  voiceId?: string;
  llmId?: string;
  systemPrompt?: string;
  description?: string;
  category?: string;
  maxSessionLengthSeconds?: number;
  languageCode?: string;
}

export interface SessionTokenRequest {
  personaConfig: PersonaConfig;
}

export async function getSessionToken(personaConfig: PersonaConfig): Promise<string> {
  if (!process.env.ANAM_API_KEY) {
    throw new Error("ANAM_API_KEY environment variable is not set");
  }

  console.log('Requesting session token with API key:', process.env.ANAM_API_KEY.substring(0, 10) + '...');
  console.log('Persona config:', personaConfig);

  const requestBody = {
    personaConfig
  };

  console.log('Request body:', JSON.stringify(requestBody, null, 2));

  const response = await fetch('https://api.anam.ai/v1/auth/session-token', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${process.env.ANAM_API_KEY}`
    },
    body: JSON.stringify(requestBody)
  });

  console.log('Response status:', response.status);
  console.log('Response headers:', Object.fromEntries(response.headers.entries()));

  if (!response.ok) {
    const error = await response.text();
    console.error('Session token error response:', error);
    throw new Error(`Failed to get session token: ${response.status} - ${error}`);
  }

  const data = await response.json();
  console.log('Session token response:', data);
  return data.sessionToken;
}

export const DEFAULT_PERSONA_CONFIG: PersonaConfig = {
  id: "cageside-commentator",
  name: "CageSide Commentator",
  avatarId: "30fa96d0-26c4-4e55-94a0-517025942e18",
  voiceId: "6bfbe25a-979d-40f3-a92b-5394170af54b",
  llmId: "0934d97d-0c3a-4f33-91b0-5e136a0ef466",
  systemPrompt: "You are an expert sports coach and commentator. Provide encouraging, actionable feedback to help athletes improve their performance. Keep responses concise and motivational.",
  description: "Expert sports coach and commentator",
  category: "Coach"
};