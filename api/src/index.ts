export interface Env {
  CONTEXT_KV: KVNamespace;
  CHANNEL_BROKER: DurableObjectNamespace;
}

/**
 * Storage format (Phase 5+):
 *   KV value = JSON.stringify({
 *     data:     string,         // plaintext or Fernet ciphertext
 *     metadata: object,         // always plaintext; may be {}
 *   })
 *
 * Legacy format (pre-Phase-5):
 *   KV value = <raw payload string>
 *
 * Peek handles both; Pull returns the stored value as-is and the SDK
 * unwraps client-side (also handling both formats).
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

    // POST /push — store {data, metadata}; optionally fan-out to a channel.
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
            })
          )
        );
      }

      return new Response(JSON.stringify({ url: pointerUrl, id, channel: channel ?? null }), {
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // GET /pull/:id — return KV value as-is (new JSON wrapper or legacy raw).
    // The SDK is responsible for unwrapping.
    if (request.method === 'GET' && url.pathname.startsWith('/pull/')) {
      const id = url.pathname.split('/')[2];
      const text = await env.CONTEXT_KV.get(id);
      if (!text) return new Response('Context not found or expired', { status: 404 });
      return new Response(text, { headers: { 'Content-Type': 'text/plain' } });
    }

    // GET /peek/:id — return only the metadata object (server-side unwrap).
    // Legacy raw entries return {}.
    if (request.method === 'GET' && url.pathname.startsWith('/peek/')) {
      const id = url.pathname.split('/')[2];
      const text = await env.CONTEXT_KV.get(id);
      if (!text) return new Response('Context not found or expired', { status: 404 });

      let metadata: Record<string, unknown> = {};
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
          metadata = parsed.metadata as Record<string, unknown>;
        }
      } catch {
        // Legacy raw entry — no metadata.
      }
      return new Response(JSON.stringify(metadata), {
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // GET /ws/:channel — upgrade and hand off to the channel's DO.
    if (request.method === 'GET' && url.pathname.startsWith('/ws/')) {
      if (request.headers.get('Upgrade') !== 'websocket') {
        return new Response('Expected WebSocket upgrade', { status: 426 });
      }
      const channel = url.pathname.slice('/ws/'.length);
      if (!channel) return new Response('Missing channel', { status: 400 });
      const stub = env.CHANNEL_BROKER.get(env.CHANNEL_BROKER.idFromName(channel));
      return stub.fetch(request);
    }

    return new Response('ContextRelay API is running.', { status: 200 });
  },
};
