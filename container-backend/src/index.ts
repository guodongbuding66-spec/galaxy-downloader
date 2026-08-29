import { Container, getRandom } from '@cloudflare/containers';
import { env as runtimeEnv } from 'cloudflare:workers';

import {
  isXhsSourceUrl,
  xhsDownloadResponse,
  xhsParseResponse,
  xhsResolverConfigured,
  xhsResolverMode,
  type XhsResolverRuntime,
} from './xhs-resolver';

interface RuntimeSecrets extends XhsResolverRuntime {
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
    'Access-Control-Expose-Headers': 'Content-Length,Content-Range,Content-Disposition,Accept-Ranges,X-Request-Id,X-Galaxy-Provider,X-Max-Stream-Bytes',
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

function sourceUrlFromRequest(url: URL): string | null {
  const value = url.searchParams.get('url')?.trim();
  return value || null;
}

function safeXhsSourceUrl(value: string | null): value is string {
  if (!value || !isXhsSourceUrl(value)) return false;
  try {
    const parsed = new URL(value);
    return ['http:', 'https:'].includes(parsed.protocol)
      && !parsed.username
      && !parsed.password;
  } catch {
    return false;
  }
}

async function containerResponse(request: Request, env: Env): Promise<Response> {
  // Stateless media work is spread across a small pool. Each Container is a
  // durable-object-backed instance and sleeps automatically when idle.
  const container = await getRandom(env.MEDIA_CONTAINER, 3);
  return container.fetch(request);
}

async function parseResponseSucceeded(response: Response): Promise<boolean> {
  if (!response.ok) return false;
  const contentType = response.headers.get('content-type')?.toLowerCase() || '';
  if (!contentType.includes('json')) return false;
  try {
    const payload = await response.clone().json() as { success?: unknown };
    return payload.success !== false;
  } catch {
    return false;
  }
}

async function augmentHealth(response: Response): Promise<Response> {
  const contentType = response.headers.get('content-type')?.toLowerCase() || '';
  if (!contentType.includes('json')) return response;

  try {
    const payload = await response.clone().json() as Record<string, unknown>;
    const headers = new Headers(response.headers);
    headers.delete('content-length');
    return Response.json({
      ...payload,
      xhsResolverConfigured: xhsResolverConfigured(runtimeSecrets),
      xhsResolverMode: xhsResolverMode(runtimeSecrets),
    }, {
      status: response.status,
      headers,
    });
  } catch {
    return response;
  }
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
    const requestId = headers.get('x-request-id') || 'unknown';
    const forwarded = new Request(request, { headers });

    if (url.pathname === '/health') {
      const response = await augmentHealth(await containerResponse(forwarded, env));
      return withCors(response, request);
    }

    const sourceUrl = sourceUrlFromRequest(url);
    const useXhsResolver = Boolean(
      safeXhsSourceUrl(sourceUrl)
      && xhsResolverConfigured(runtimeSecrets),
    );

    if (useXhsResolver && sourceUrl && url.pathname === '/api/parse') {
      if (xhsResolverMode(runtimeSecrets) === 'prefer') {
        const specialized = await xhsParseResponse(request, sourceUrl, runtimeSecrets, requestId);
        if (specialized.ok) return withCors(specialized, request);

        const fallback = await containerResponse(forwarded, env);
        return withCors(await parseResponseSucceeded(fallback) ? fallback : specialized, request);
      }

      const primary = await containerResponse(forwarded, env);
      if (await parseResponseSucceeded(primary)) return withCors(primary, request);

      const specialized = await xhsParseResponse(request, sourceUrl, runtimeSecrets, requestId);
      return withCors(specialized.ok ? specialized : primary, request);
    }

    if (useXhsResolver && sourceUrl && url.pathname === '/api/download') {
      const specialized = await xhsDownloadResponse(request, sourceUrl, runtimeSecrets, requestId);
      if (specialized?.ok || specialized?.status === 206 || specialized?.status === 413) {
        return withCors(specialized, request);
      }

      const fallback = await containerResponse(forwarded, env);
      if (fallback.ok || fallback.status === 206) return withCors(fallback, request);
      return withCors(specialized || fallback, request);
    }

    const response = await containerResponse(forwarded, env);
    return withCors(response, request);
  },
};
