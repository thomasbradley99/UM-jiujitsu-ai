import express from 'express';
import cors from 'cors';
import { config } from 'dotenv';

// Load environment variables from .env.local
config({ path: '.env.local' });

const app = express();
const PORT = process.env.PORT || 3001;

app.use(cors({
  origin: true, // Allow all origins during development
  methods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
  allowedHeaders: ['Content-Type', 'Authorization'],
  credentials: true,
  optionsSuccessStatus: 200 // Some legacy browsers choke on 204
}));
app.use(express.json());

// API endpoint to get session token with persona configuration
app.post('/api/anam/session-token', async (req, res) => {
  try {
    const { personaConfig } = req.body;
    
    if (!process.env.ANAM_API_KEY) {
      return res.status(500).json({ error: 'ANAM_API_KEY not configured' });
    }

    if (!personaConfig) {
      return res.status(400).json({ error: 'personaConfig is required' });
    }

    console.log('Creating session token with persona config:', JSON.stringify(personaConfig, null, 2));

    // Create session token with the provided persona configuration
    const sessionResponse = await fetch('https://api.anam.ai/v1/auth/session-token', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${process.env.ANAM_API_KEY}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        personaConfig
      })
    });

    if (!sessionResponse.ok) {
      const errorText = await sessionResponse.text();
      console.error('Failed to get session token:', errorText);
      return res.status(sessionResponse.status).json({ 
        error: `Failed to get session token: ${errorText}` 
      });
    }

    const sessionData = await sessionResponse.json();
    console.log('Session token created successfully for:', personaConfig.name);

    res.json({
      sessionToken: sessionData.sessionToken
    });

  } catch (error) {
    console.error('Server error:', error);
    res.status(500).json({ 
      error: `Server error: ${error.message}` 
    });
  }
});

app.listen(PORT, () => {
  console.log(`API server running on http://localhost:${PORT}`);
});