export interface Env {
  CONTEXT_KV: KVNamespace;
  /** API_KEYS_KV is optional — when present, authentication is enforced.
   *  Self-hosted deployments without this binding run in open mode. */
  API_KEYS_KV: KVNamespace | undefined;
  CHANNEL_BROKER: DurableObjectNamespace;
  /** Cloud dashboard base URL for async usage reporting. */
  CLOUD_URL: string | undefined;
  /** Shared secret for worker→cloud internal calls. Set via `wrangler secret put INTERNAL_SECRET`. */
  INTERNAL_SECRET: string | undefined;
}

interface KeyEntry {
  keyId: string;
  userId: string;
  plan: string;
}

async function sha256Hex(text: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return Array.from(new Uint8Array(buf))
    .map(b => b.toString(16).padStart(2, '0'))
    .join('');
}

async function authenticate(request: Request, env: Env): Promise<KeyEntry | null> {
  const auth = request.headers.get('Authorization') ?? '';
  if (!auth.startsWith('Bearer ')) return null;
  const token = auth.slice(7).trim();
  if (!token) return null;

  const hash = await sha256Hex(token);
  const raw = await env.API_KEYS_KV!.get(`keyhash:${hash}`);
  if (!raw) return null;

  try {
    return JSON.parse(raw) as KeyEntry;
  } catch {
    return null;
  }
}

function reportUsage(
  env: Env,
  keyId: string,
  operation: 'PUSH' | 'PULL' | 'PEEK' | 'SUBSCRIBE',
  bytes: number,
): Promise<void> {
  if (!env.CLOUD_URL || !env.INTERNAL_SECRET) return Promise.resolve();
  return fetch(`${env.CLOUD_URL}/api/internal/usage`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-internal-secret': env.INTERNAL_SECRET,
    },
    body: JSON.stringify({ keyId, operation, bytes }),
  })
    .then(() => undefined)
    .catch(() => undefined); // Best-effort — never fail the main request.
}

/**
 * Storage format (Phase 5+):
 *   KV value = JSON.stringify({ data: string, metadata: object })
 *
 * Legacy format (pre-Phase-5):
 *   KV value = <raw payload string>
 */

export class ChannelBroker {
  constructor(private state: DurableObjectState, private env: Env) {}

  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);

    if (request.headers.get('Upgrade') === 'websocket') {
      const pair = new WebSocketPair();
      const [client, server] = Object.values(pair) as [WebSocket, WebSocket];
      this.state.acceptWebSocket(server);
      return new Response(null, { status: 101, webSocket: client });
    }

    if (request.method === 'POST' && url.pathname === '/broadcast') {
      const body = (await request.json()) as { url?: string };
      if (!body.url) return new Response('Missing url', { status: 400 });

      const msg = JSON.stringify({ url: body.url, ts: Date.now() });
      let delivered = 0;
      for (const ws of this.state.getWebSockets()) {
        try {
          ws.send(msg);
          delivered++;
        } catch {
          // Best-effort; dead sockets get cleaned up by the runtime.
        }
      }
      return new Response(JSON.stringify({ delivered }), {
        headers: { 'Content-Type': 'application/json' },
      });
    }

    return new Response('Not found', { status: 404 });
  }

  async webSocketMessage(_ws: WebSocket, _msg: string | ArrayBuffer) {}

  async webSocketClose(ws: WebSocket, code: number, _reason: string, _wasClean: boolean) {
    try {
      ws.close(code, 'closing');
    } catch {
      // ignore
    }
  }
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);

    // Health check — always open.
    if (url.pathname === '/' || url.pathname === '') {
      return new Response('ContextRelay API is running.', { status: 200 });
    }

    // Auth gate — only enforced when API_KEYS_KV is bound.
    // Deployments without the binding run in open/self-hosted mode.
    let keyEntry: KeyEntry | null = null;
    if (env.API_KEYS_KV) {
      keyEntry = await authenticate(request, env);
      if (!keyEntry) {
        return new Response(
          JSON.stringify({ error: 'Missing or invalid API key' }),
          { status: 401, headers: { 'Content-Type': 'application/json' } },
        );
      }
    }

    // POST /push
    if (request.method === 'POST' && url.pathname === '/push') {
      const contentType = request.headers.get('Content-Type') || '';
      let dataField: string;
      let channel: string | undefined;
      let metadata: Record<string, unknown> = {};

      if (contentType.includes('application/json')) {
        let parsed: { data?: unknown; channel?: unknown; metadata?: unknown };
        try {
          parsed = (await request.json()) as typeof parsed;
        } catch {
          return new Response('Invalid JSON body', { status: 400 });
        }
        if (typeof parsed.data !== 'string') {
          return new Response('JSON body must include "data" as a string', { status: 400 });
        }
        dataField = parsed.data;
        if (typeof parsed.channel === 'string' && parsed.channel.length > 0) {
          channel = parsed.channel;
        }
        if (
          parsed.metadata &&
          typeof parsed.metadata === 'object' &&
          !Array.isArray(parsed.metadata)
        ) {
          metadata = parsed.metadata as Record<string, unknown>;
        }
      } else {
        dataField = await request.text();
      }

      if (!dataField) return new Response('Missing body', { status: 400 });

      const id = crypto.randomUUID();
      const stored = JSON.stringify({ data: dataField, metadata });
      await env.CONTEXT_KV.put(id, stored, { expirationTtl: 86400 });
      const pointerUrl = `${url.origin}/pull/${id}`;

      if (channel) {
        const stub = env.CHANNEL_BROKER.get(env.CHANNEL_BROKER.idFromName(channel));
        ctx.waitUntil(
          stub.fetch(
            new Request('https://do.internal/broadcast', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ url: pointerUrl }),
            }),
          ),
        );
      }

      if (keyEntry) {
        ctx.waitUntil(reportUsage(env, keyEntry.keyId, 'PUSH', dataField.length));
      }

      return new Response(JSON.stringify({ url: pointerUrl, id, channel: channel ?? null }), {
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // GET /pull/:id
    if (request.method === 'GET' && url.pathname.startsWith('/pull/')) {
      const id = url.pathname.split('/')[2];
      const text = await env.CONTEXT_KV.get(id);
      if (!text) return new Response('Context not found or expired', { status: 404 });

      if (keyEntry) {
        ctx.waitUntil(reportUsage(env, keyEntry.keyId, 'PULL', text.length));
      }

      return new Response(text, { headers: { 'Content-Type': 'text/plain' } });
    }

    // GET /peek/:id
    if (request.method === 'GET' && url.pathname.startsWith('/peek/')) {
      const id = url.pathname.split('/')[2];
      const text = await env.CONTEXT_KV.get(id);
      if (!text) return new Response('Context not found or expired', { status: 404 });

      let meta: Record<string, unknown> = {};
      try {
        const parsed = JSON.parse(text);
        if (
          parsed &&
          typeof parsed === 'object' &&
          !Array.isArray(parsed) &&
          parsed.metadata &&
          typeof parsed.metadata === 'object' &&
          !Array.isArray(parsed.metadata)
        ) {
          meta = parsed.metadata as Record<string, unknown>;
        }
      } catch {
        // Legacy raw entry — no metadata.
      }

      if (keyEntry) {
        ctx.waitUntil(reportUsage(env, keyEntry.keyId, 'PEEK', 0));
      }

      return new Response(JSON.stringify(meta), {
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // GET /ws/:channel
    if (request.method === 'GET' && url.pathname.startsWith('/ws/')) {
      if (request.headers.get('Upgrade') !== 'websocket') {
        return new Response('Expected WebSocket upgrade', { status: 426 });
      }
      const channel = url.pathname.slice('/ws/'.length);
      if (!channel) return new Response('Missing channel', { status: 400 });
      const stub = env.CHANNEL_BROKER.get(env.CHANNEL_BROKER.idFromName(channel));
      return stub.fetch(request);
    }

    return new Response('Not found', { status: 404 });
  },
};
