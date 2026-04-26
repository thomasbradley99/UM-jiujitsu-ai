import express from 'express';
import cors from 'cors';
import path from 'path';
import { fileURLToPath } from 'url';
import { readFileSync, existsSync } from 'fs';
import { GoogleGenAI, Type } from '@google/genai';
import { config } from 'dotenv';

// Load environment variables — .env.local overrides .env (local dev only)
config({ path: '.env' });
config({ path: '.env.local', override: true });

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const app = express();
const PORT = Number.parseInt(process.env.PORT ?? '10000', 10);
const HOST = process.env.HOST || '0.0.0.0';
const GEMINI_API_KEY = process.env.GEMINI_API_KEY || process.env.VITE_GEMINI_API_KEY || process.env.API_KEY;
const gemini = GEMINI_API_KEY ? new GoogleGenAI({ apiKey: GEMINI_API_KEY }) : null;

app.disable('x-powered-by');
app.set('trust proxy', 1);

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

// ---------------------------------------------------------------------------
// Research Lab API — serves website/data/ as typed JSON endpoints
// ---------------------------------------------------------------------------
const WEB_DATA = path.join(__dirname, 'website', 'data');

function readLabJson(rel) {
  const full = path.join(WEB_DATA, rel);
  if (!existsSync(full)) return null;
  return JSON.parse(readFileSync(full, 'utf8'));
}

function deriveWinner(game) {
  if (!game?.submissions?.length) return 'No clear winner';
  const counts = game.submissions.reduce((acc, sub) => {
    acc[sub.submitter] = (acc[sub.submitter] || 0) + 1;
    return acc;
  }, {});
  const ordered = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  if (ordered.length < 2 || ordered[0][1] > ordered[1][1]) return ordered[0][0];
  return 'Draw';
}

const reviewResponseSchema = {
  type: Type.OBJECT,
  properties: {
    headline: { type: Type.STRING },
    summary: { type: Type.STRING },
    winner: { type: Type.STRING },
    winner_reason: { type: Type.STRING },
    strengths: { type: Type.ARRAY, items: { type: Type.STRING } },
    improvements: { type: Type.ARRAY, items: { type: Type.STRING } },
    tactical_focus: { type: Type.ARRAY, items: { type: Type.STRING } },
    confidence: { type: Type.STRING, enum: ['high', 'medium', 'low'] },
  },
  required: ['headline', 'summary', 'winner', 'winner_reason', 'strengths', 'improvements', 'tactical_focus', 'confidence'],
};

app.get('/api/lab/manifest', (_req, res) => {
  const data = readLabJson('manifest.json');
  if (!data) return res.status(404).json({ error: 'manifest.json not found' });
  res.json(data);
});

app.get('/api/lab/games', (_req, res) => {
  const data = readLabJson(path.join('games', 'index.json'));
  if (!data) return res.status(404).json({ error: 'games index not found' });
  res.json(data);
});

app.get('/api/lab/games/:gameId', (req, res) => {
  const games = readLabJson(path.join('games', 'index.json'));
  if (!games) return res.status(404).json({ error: 'games index not found' });
  const game = games.find((g) => g.id === req.params.gameId);
  if (!game) return res.status(404).json({ error: `Game '${req.params.gameId}' not found` });
  res.json(game);
});

app.get('/api/lab/runs', (_req, res) => {
  const data = readLabJson(path.join('runs', 'index.json'));
  if (!data) return res.status(404).json({ error: 'runs index not found' });
  res.json(data);
});

app.get('/api/lab/runs/:arcId', (req, res) => {
  const data = readLabJson(path.join('runs', req.params.arcId, 'index.json'));
  if (!data) return res.status(404).json({ error: `Arc '${req.params.arcId}' not found` });
  res.json(data);
});

app.get('/api/lab/cross-eval', (_req, res) => {
  const data = readLabJson(path.join('cross_eval', 'index.json'));
  if (!data) return res.status(404).json({ error: 'cross-eval index not found' });
  res.json(data);
});

app.post('/api/lab/review/:gameId', async (req, res) => {
  if (!gemini) {
    return res.status(503).json({ error: 'GEMINI_API_KEY not configured for lab reviews' });
  }

  const games = readLabJson(path.join('games', 'index.json'));
  if (!games) return res.status(404).json({ error: 'games index not found' });
  const game = games.find((entry) => entry.id === req.params.gameId);
  if (!game) return res.status(404).json({ error: `Game '${req.params.gameId}' not found` });

  const runs = readLabJson(path.join('runs', 'index.json')) || [];
  const relatedRuns = runs
    .filter((run) => run.video === game.id)
    .sort((a, b) => (b.peak_f1 || 0) - (a.peak_f1 || 0));
  const bestRun = relatedRuns[0] || null;

  const crossEval = readLabJson(path.join('cross_eval', 'index.json')) || [];
  const evalRow = crossEval.find((row) => row.game === game.id) || null;

  const prompt = `You are reviewing a Brazilian Jiu-Jitsu fight analysis entry for a research dashboard.

Return a compact JSON review for coaches and analysts.

GAME
${JSON.stringify(game, null, 2)}

BEST_RUN
${JSON.stringify(bestRun, null, 2)}

CROSS_EVAL_ROW
${JSON.stringify(evalRow, null, 2)}

KNOWN WINNER
${deriveWinner(game)}

Write the review in a factual, technical tone. Use the metrics when available.
Do not mention missing data unless necessary. Improvements should be actionable.
Strengths should reflect what the data supports.
Tactical focus should be short coaching bullets.`;

  try {
    const response = await gemini.models.generateContent({
      model: 'gemini-2.5-flash',
      contents: [{ text: prompt }],
      config: {
        responseMimeType: 'application/json',
        responseSchema: reviewResponseSchema,
      },
    });

    return res.json(JSON.parse((response.text || '').trim()));
  } catch (error) {
    console.error('Failed to generate lab review:', error);
    return res.status(500).json({ error: 'Failed to generate Gemini review' });
  }
});

// Serve experiment videos from website/public/
app.use('/website/public', express.static(path.join(__dirname, 'website', 'public')));

// ---------------------------------------------------------------------------
// Live analysis SSE stream — replays a flywheel arc with artificial timing
// so the frontend gets a "live results" experience without a Python service.
//
// GET /api/analysis/stream/:arcId?speed=1.0
//   Streams newline-delimited SSE frames (text/event-stream).
//   Each frame is a StreamFrame JSON payload (mirrors backend.py).
// ---------------------------------------------------------------------------
app.get('/api/analysis/stream/:arcId', async (req, res) => {
  const arcId = req.params.arcId;
  const speed = Math.min(10, Math.max(0.1, parseFloat(req.query.speed) || 1.0));

  // Load arc data
  let arc;
  try {
    const arcPath = path.join(WEB_DATA, 'runs', arcId, 'index.json');
    if (!existsSync(arcPath)) {
      res.writeHead(404, { 'Content-Type': 'application/json' });
      return res.end(JSON.stringify({ error: `Arc '${arcId}' not found` }));
    }
    arc = JSON.parse(readFileSync(arcPath, 'utf-8'));
  } catch (err) {
    res.writeHead(500, { 'Content-Type': 'application/json' });
    return res.end(JSON.stringify({ error: 'Failed to load arc data' }));
  }

  // Load ground-truth game submissions (best-effort)
  let game = null;
  try {
    const gamesPath = path.join(WEB_DATA, 'games', 'index.json');
    if (existsSync(gamesPath)) {
      const games = JSON.parse(readFileSync(gamesPath, 'utf-8'));
      game = games.find((g) => g.id === arc.video) ?? null;
    }
  } catch { /* proceed without game data */ }

  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
    'X-Accel-Buffering': 'no',
  });

  let aborted = false;
  req.on('close', () => { aborted = true; });

  const startMs = Date.now();
  const elapsed = () => parseFloat(((Date.now() - startMs) / 1000).toFixed(3));
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  const sendFrame = (frame) => {
    if (!aborted) res.write(`data: ${JSON.stringify(frame)}\n\n`);
  };

  // Helper: build a stable confidence value from technique name
  const techniqueConfidence = (technique, f1) => {
    const jitter = (technique.split('').reduce((a, c) => a + c.charCodeAt(0), 0) % 13 - 6) / 100;
    return Math.round(Math.min(1, Math.max(0, f1 + jitter)) * 10000) / 10000;
  };

  // Heartbeat
  sendFrame({
    frame_type: 'heartbeat', elapsed_sec: 0, total_events: 0,
    events: [], metrics_history: [],
    message: `Starting replay of '${arc.label}' · ${arc.iterations.length} iterations`,
  });
  await sleep(500 / speed);

  const eventsSoFar = [];
  const metricsHistory = [];

  for (const it of arc.iterations) {
    if (aborted) break;

    const liveMet = {
      iteration: it.iteration,
      prompt_label: it.prompt_version_id.slice(0, 28),
      precision: it.precision,
      recall: it.recall,
      f1: it.f1,
      f1_pct: `${(it.f1 * 100).toFixed(1)}%`,
      n_gt: it.n_gt,
      n_pred: it.n_pred,
      matched: it.n_matched,
      hallucinations: it.n_hallucinations,
      hallucination_rate: parseFloat((it.n_hallucinations / Math.max(it.n_pred, 1)).toFixed(4)),
      activated: it.activated,
    };
    metricsHistory.push(liveMet);

    // Emit individual event arrivals for newly visible GT submissions
    if (game) {
      const visibleSubs = game.submissions.slice(0, it.n_matched);
      for (const sub of visibleSubs) {
        if (aborted) break;
        const alreadyHas = eventsSoFar.some(
          (e) => e.timestamp_sec === sub.timestamp && e.technique === sub.technique
        );
        if (!alreadyHas) {
          const ev = {
            event_id: Math.random().toString(36).slice(2, 10),
            timestamp_sec: sub.timestamp,
            technique: sub.technique,
            submitter: sub.submitter,
            submittee: sub.submittee,
            confidence: techniqueConfidence(sub.technique, it.f1),
            confidence_pct: `${Math.round(techniqueConfidence(sub.technique, it.f1) * 100)}%`,
            notes: sub.notes ?? null,
          };
          eventsSoFar.push(ev);
          sendFrame({
            frame_type: 'event',
            elapsed_sec: elapsed(),
            total_events: eventsSoFar.length,
            events: [...eventsSoFar],
            metrics_history: [...metricsHistory],
          });
          await sleep(400 / speed);
        }
      }
    }

    // Metrics snapshot
    sendFrame({
      frame_type: 'metrics',
      elapsed_sec: elapsed(),
      total_events: eventsSoFar.length,
      events: [...eventsSoFar],
      metrics_history: [...metricsHistory],
      message: `Iter ${it.iteration}: F1 ${(it.f1 * 100).toFixed(1)}% | P ${(it.precision * 100).toFixed(1)}% | R ${(it.recall * 100).toFixed(1)}%`,
    });
    await sleep(1800 / speed);
  }

  if (!aborted) {
    sendFrame({
      frame_type: 'complete',
      elapsed_sec: elapsed(),
      total_events: eventsSoFar.length,
      events: [...eventsSoFar],
      metrics_history: [...metricsHistory],
      message: 'Analysis complete ✓',
    });
  }
  res.end();
});

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
  // Return index.html for unmatched non-API GET routes so the SPA router works.
  app.get(/^(?!\/api(?:\/|$)).*/, (_req, res) => {
    res.sendFile(path.join(distPath, 'index.html'));
  });
}

const server = app.listen(PORT, HOST, () => {
  console.log(`Server listening on http://${HOST}:${PORT} (${process.env.NODE_ENV || 'development'})`);
});

// Avoid 502 Bad Gateway on Render — keep connections alive longer than
// the platform's 75-second idle timeout on the load balancer
server.keepAliveTimeout = 120000; // 120 s
server.headersTimeout = 121000;   // must be > keepAliveTimeout

const shutdown = (signal) => {
  console.log(`${signal} received, shutting down gracefully`);
  server.close((error) => {
    if (error) {
      console.error('Error during shutdown:', error);
      process.exit(1);
    }

    process.exit(0);
  });
};

process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));