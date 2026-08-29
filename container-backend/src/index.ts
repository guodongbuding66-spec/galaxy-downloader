import { Container, getRandom } from '@cloudflare/containers';
import { env as runtimeEnv } from 'cloudflare:workers';

interface RuntimeSecrets {
  YTDLP_COOKIES_B64?: string;
  YTDLP_COOKIE_POLICY?: string;
  YTDLP_TWITCH_ALLOW_COOKIES?: string;
  YTDLP_PROXY?: string;
  YTDLP_YOUTUBE_PROXY?: string;
  YTDLP_XHS_PROXY?: string;
  YTDLP_RUMBLE_PROXY?: string;
  YTDLP_USER_AGENT?: string;
  YTDLP_IMPERSONATE?: string;
  YTDLP_SOCKET_TIMEOUT?: string;
  YTDLP_EXTRACTOR_RETRIES?: string;
  YTDLP_RETRIES?: string;
  YTDLP_FRAGMENT_RETRIES?: string;
  YTDLP_CONCURRENT_FRAGMENTS?: string;
  ALLOWED_ORIGINS?: string;
}

interface Env extends RuntimeSecrets {
  MEDIA_CONTAINER: DurableObjectNamespace<MediaContainer>;
}

const runtimeSecrets = runtimeEnv as unknown as RuntimeSecrets;
const DEFAULT_ALLOWED_ORIGINS = [
  'https://galaxy-downloader.guodongbuding66.workers.dev',
  'http://localhost:3010',
  'http://127.0.0.1:3010',
];

function configuredOrigins(): string[] {
  const configured = runtimeSecrets.ALLOWED_ORIGINS
    ?.split(',')
    .map((origin) => origin.trim())
    .filter(Boolean);
  return configured?.length ? configured : DEFAULT_ALLOWED_ORIGINS;
}

export class MediaContainer extends Container {
  defaultPort = 8080;
  sleepAfter = '10m';
  enableInternet = true;

  envVars = {
    YTDLP_COOKIES_B64: runtimeSecrets.YTDLP_COOKIES_B64 || '',
    YTDLP_COOKIE_POLICY: runtimeSecrets.YTDLP_COOKIE_POLICY || 'when_needed',
    YTDLP_TWITCH_ALLOW_COOKIES: runtimeSecrets.YTDLP_TWITCH_ALLOW_COOKIES || '0',
    YTDLP_PROXY: runtimeSecrets.YTDLP_PROXY || '',
    YTDLP_YOUTUBE_PROXY: runtimeSecrets.YTDLP_YOUTUBE_PROXY || '',
    YTDLP_XHS_PROXY: runtimeSecrets.YTDLP_XHS_PROXY || '',
    YTDLP_RUMBLE_PROXY: runtimeSecrets.YTDLP_RUMBLE_PROXY || '',
    YTDLP_USER_AGENT: runtimeSecrets.YTDLP_USER_AGENT || '',
    YTDLP_IMPERSONATE: runtimeSecrets.YTDLP_IMPERSONATE || 'chrome',
    YTDLP_SOCKET_TIMEOUT: runtimeSecrets.YTDLP_SOCKET_TIMEOUT || '30',
    YTDLP_EXTRACTOR_RETRIES: runtimeSecrets.YTDLP_EXTRACTOR_RETRIES || '3',
    YTDLP_RETRIES: runtimeSecrets.YTDLP_RETRIES || '3',
    YTDLP_FRAGMENT_RETRIES: runtimeSecrets.YTDLP_FRAGMENT_RETRIES || '3',
    YTDLP_CONCURRENT_FRAGMENTS: runtimeSecrets.YTDLP_CONCURRENT_FRAGMENTS || '4',
    ALLOWED_ORIGINS: configuredOrigins().join(','),
  };

  override onError(error: unknown) {
    console.error('[media-container]', error);
  }
}

function corsHeaders(request: Request): HeadersInit {
  const origin = request.headers.get('origin') || '';
  const allowedOrigins = configuredOrigins();
  const allowed = new Set(allowedOrigins);
  return {
    'Access-Control-Allow-Origin': allowed.has(origin) ? origin : allowedOrigins[0],
    'Access-Control-Allow-Methods': 'GET,HEAD,OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type,Range,X-Request-Id',
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
    if (!headers.has('x-request-id')) {
      headers.set('x-request-id', crypto.randomUUID());
    }
    const forwarded = new Request(request, { headers });

    // Stateless media work is spread across a small pool. Each Container is a
    // durable-object-backed instance and sleeps automatically when idle.
    const container = await getRandom(env.MEDIA_CONTAINER, 3);
    const response = await container.fetch(forwarded);
    return withCors(response, request);
  },
};
