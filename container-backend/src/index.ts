import { Container, getRandom } from '@cloudflare/containers';
import { env as runtimeEnv } from 'cloudflare:workers';

interface RuntimeSecrets {
  YTDLP_COOKIES_B64?: string;
  YTDLP_PROXY?: string;
  YTDLP_USER_AGENT?: string;
}

interface Env extends RuntimeSecrets {
  MEDIA_CONTAINER: DurableObjectNamespace<MediaContainer>;
}

const runtimeSecrets = runtimeEnv as unknown as RuntimeSecrets;

export class MediaContainer extends Container {
  defaultPort = 8080;
  sleepAfter = '10m';
  enableInternet = true;

  envVars = {
    YTDLP_COOKIES_B64: runtimeSecrets.YTDLP_COOKIES_B64 || '',
    YTDLP_PROXY: runtimeSecrets.YTDLP_PROXY || '',
    YTDLP_USER_AGENT: runtimeSecrets.YTDLP_USER_AGENT || '',
    ALLOWED_ORIGINS: [
      'https://galaxy-downloader.guodongbuding66.workers.dev',
      'http://localhost:3010',
      'http://127.0.0.1:3010',
    ].join(','),
  };

  override onError(error: unknown) {
    console.error('[media-container]', error);
  }
}

function corsHeaders(request: Request): HeadersInit {
  const origin = request.headers.get('origin') || '';
  const allowed = new Set([
    'https://galaxy-downloader.guodongbuding66.workers.dev',
    'http://localhost:3010',
    'http://127.0.0.1:3010',
  ]);
  return {
    'Access-Control-Allow-Origin': allowed.has(origin) ? origin : 'https://galaxy-downloader.guodongbuding66.workers.dev',
    'Access-Control-Allow-Methods': 'GET,HEAD,OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type,Range',
    'Access-Control-Expose-Headers': 'Content-Length,Content-Range,Content-Disposition,Accept-Ranges,X-Request-Id',
    Vary: 'Origin',
  };
}

function withCors(response: Response, request: Request): Response {
  const headers = new Headers(response.headers);
  for (const [key, value] of Object.entries(corsHeaders(request))) {
    headers.set(key, String(value));
  }
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders(request) });
    }

    if (!['GET', 'HEAD'].includes(request.method)) {
      return withCors(Response.json({ success: false, error: 'Method not allowed' }, { status: 405 }), request);
    }

    if (url.pathname !== '/health' && !url.pathname.startsWith('/api/')) {
      return withCors(Response.json({
        success: false,
        error: 'Not found',
        endpoints: ['/health', '/api/parse', '/api/download'],
      }, { status: 404 }), request);
    }

    const headers = new Headers(request.headers);
    headers.set('x-public-base-url', `${url.protocol}//${url.host}`);
    headers.set('x-request-id', crypto.randomUUID());
    const forwarded = new Request(request, { headers });

    // Stateless media work is spread across a small pool. Each Container is a
    // durable-object-backed instance and sleeps automatically when idle.
    const container = await getRandom(env.MEDIA_CONTAINER, 3);
    const response = await container.fetch(forwarded);
    return withCors(response, request);
  },
};
