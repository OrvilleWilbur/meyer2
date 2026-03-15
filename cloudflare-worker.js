/**
 * Cloudflare Worker — API-Proxy für KH-Brand-Monitor
 *
 * Zwei Endpoints:
 *   POST /           → Chat (Anthropic API Proxy)
 *   POST /candidates → Duplikat-Entscheidungen nach GitHub schreiben
 *
 * Setup:
 * 1. Gehe zu dash.cloudflare.com → Workers & Pages → Create Worker
 * 2. Füge diesen Code ein
 * 3. Unter Settings → Variables → Environment Variables:
 *    - ANTHROPIC_API_KEY = dein Anthropic API Key
 *    - GITHUB_TOKEN = Personal Access Token (repo scope) für OrvilleWilbur/meyer2
 * 4. Deploy
 * 5. Worker-URL in die Website unter "Proxy konfigurieren" eintragen
 */

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
  'Access-Control-Max-Age': '86400',
};

const GITHUB_REPO = 'OrvilleWilbur/meyer2';
const CANDIDATES_PATH = 'data/merge_candidates.json';

function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json', ...CORS_HEADERS },
  });
}

// ── Chat Endpoint (Anthropic API Proxy) ──

async function handleChat(body, env) {
  if (!body.messages || !body.model) {
    return jsonResponse({ error: 'Invalid request: messages and model required' }, 400);
  }

  const response = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'x-api-key': env.ANTHROPIC_API_KEY,
      'anthropic-version': '2023-06-01',
      'content-type': 'application/json',
    },
    body: JSON.stringify({
      model: body.model || 'claude-haiku-4-5-20251001',
      max_tokens: body.max_tokens || 1024,
      system: body.system || '',
      messages: body.messages,
    }),
  });

  const data = await response.json();
  return jsonResponse(data, response.status);
}

// ── Candidates Endpoint (GitHub API Write) ──

async function handleCandidates(body, env) {
  if (!env.GITHUB_TOKEN) {
    return jsonResponse({ error: 'GITHUB_TOKEN not configured' }, 500);
  }

  if (!body.candidates) {
    return jsonResponse({ error: 'Invalid request: candidates object required' }, 400);
  }

  // Schritt 1: Aktuelle Datei von GitHub lesen (brauchen SHA für Update)
  const getResp = await fetch(
    `https://api.github.com/repos/${GITHUB_REPO}/contents/${CANDIDATES_PATH}`,
    {
      headers: {
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        Accept: 'application/vnd.github.v3+json',
        'User-Agent': 'KH-Brand-Monitor-Worker',
      },
    }
  );

  let currentSha = null;
  let currentData = { pending: [], confirmed: [], rejected: [] };

  if (getResp.ok) {
    const fileInfo = await getResp.json();
    currentSha = fileInfo.sha;
    try {
      currentData = JSON.parse(atob(fileInfo.content));
    } catch (e) {
      // Datei kaputt — wird überschrieben
    }
  }

  // Schritt 2: Entscheidungen anwenden
  const decisions = body.candidates;

  // Neue confirmed/rejected hinzufügen
  if (decisions.confirmed && decisions.confirmed.length > 0) {
    if (!currentData.confirmed) currentData.confirmed = [];
    currentData.confirmed.push(...decisions.confirmed);
  }
  if (decisions.rejected && decisions.rejected.length > 0) {
    if (!currentData.rejected) currentData.rejected = [];
    currentData.rejected.push(...decisions.rejected);
  }

  // Entschiedene aus pending entfernen
  const decidedHashes = new Set();
  for (const d of [...(decisions.confirmed || []), ...(decisions.rejected || [])]) {
    const pair = (d.hashes || []).sort().join('|');
    if (pair) decidedHashes.add(pair);
  }
  if (currentData.pending) {
    currentData.pending = currentData.pending.filter(p => {
      const pair = (p.hashes || []).sort().join('|');
      return !decidedHashes.has(pair);
    });
  }

  // Schritt 3: Zurück nach GitHub schreiben
  const content = btoa(unescape(encodeURIComponent(JSON.stringify(currentData, null, 2))));

  const putBody = {
    message: `Duplikat-Entscheidungen: ${decisions.confirmed?.length || 0} bestätigt, ${decisions.rejected?.length || 0} abgelehnt`,
    content,
    committer: {
      name: 'KH-Brand-Monitor',
      email: 'bot@kh-brand-monitor',
    },
  };
  if (currentSha) putBody.sha = currentSha;

  const putResp = await fetch(
    `https://api.github.com/repos/${GITHUB_REPO}/contents/${CANDIDATES_PATH}`,
    {
      method: 'PUT',
      headers: {
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        Accept: 'application/vnd.github.v3+json',
        'Content-Type': 'application/json',
        'User-Agent': 'KH-Brand-Monitor-Worker',
      },
      body: JSON.stringify(putBody),
    }
  );

  if (!putResp.ok) {
    const err = await putResp.text();
    return jsonResponse({ error: `GitHub write failed: ${putResp.status}`, details: err }, 500);
  }

  return jsonResponse({
    success: true,
    confirmed: decisions.confirmed?.length || 0,
    rejected: decisions.rejected?.length || 0,
    pending_remaining: currentData.pending?.length || 0,
  });
}

// ── Router ──

export default {
  async fetch(request, env) {
    // CORS Preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: CORS_HEADERS });
    }

    if (request.method !== 'POST') {
      return jsonResponse({ error: 'Only POST allowed' }, 405);
    }

    try {
      const url = new URL(request.url);
      const body = await request.json();

      // Route: /candidates → Duplikat-Entscheidungen
      if (url.pathname === '/candidates') {
        return handleCandidates(body, env);
      }

      // Default Route: / → Chat
      return handleChat(body, env);

    } catch (e) {
      return jsonResponse({ error: e.message }, 500);
    }
  },
};
