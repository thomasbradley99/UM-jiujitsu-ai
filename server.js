import express from 'express';
import cors from 'cors';
import path from 'path';
import { fileURLToPath } from 'url';
import { config } from 'dotenv';

// Load environment variables — .env.local overrides .env (local dev only)
config({ path: '.env' });
config({ path: '.env.local', override: true });

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const app = express();
// Render sets PORT automatically; default to 10000 to match Render's default
const PORT = process.env.PORT || 10000;
const HOST = '0.0.0.0'; // Bind to all interfaces — required for Render

// In production restrict CORS to the service's own origin; in dev allow all
const allowedOrigins = process.env.CORS_ORIGIN
  ? process.env.CORS_ORIGIN.split(',').map(o => o.trim())
  : true; // allow all in local dev

app.use(cors({
  origin: allowedOrigins,
  methods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
  allowedHeaders: ['Content-Type', 'Authorization'],
  credentials: true,
  optionsSuccessStatus: 200
}));
app.use(express.json());

// Health check — used by Render to verify the service is live
app.get('/api/health', (_req, res) => res.json({ status: 'ok' }));

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

// Serve Vite production build from dist/ in production
if (process.env.NODE_ENV === 'production') {
  const distPath = path.join(__dirname, 'dist');
  app.use(express.static(distPath));
  // Return index.html for any unmatched route so the SPA router works
  app.get('/{*splat}', (_req, res) => {
    res.sendFile(path.join(distPath, 'index.html'));
  });
}

const server = app.listen(PORT, HOST, () => {
  console.log(`Server listening on http://${HOST}:${PORT}`);
});

// Avoid 502 Bad Gateway on Render — keep connections alive longer than
// the platform's 75-second idle timeout on the load balancer
server.keepAliveTimeout = 120000; // 120 s
server.headersTimeout = 121000;   // must be > keepAliveTimeout