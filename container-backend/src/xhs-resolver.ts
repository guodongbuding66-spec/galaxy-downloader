export interface XhsResolverRuntime {
  XHS_RESOLVER_URL?: string;
  XHS_RESOLVER_TOKEN?: string;
  XHS_RESOLVER_MODE?: string;
  XHS_RESOLVER_TIMEOUT_MS?: string;
  XHS_MEDIA_HOST_SUFFIXES?: string;
  XHS_MAX_STREAM_BYTES?: string;
  YTDLP_USER_AGENT?: string;
}

type JsonObject = Record<string, unknown>;

type XhsMediaItem = {
  index: number;
  kind: string;
  url: string;
  suffix: string;
  previewUrl: string | null;
};

const DEFAULT_TIMEOUT_MS = 20_000;
const DEFAULT_MAX_STREAM_BYTES = 6 * 1024 * 1024 * 1024;
const MAX_RESOLVER_RESPONSE_CHARS = 2 * 1024 * 1024;
const DEFAULT_MEDIA_HOST_SUFFIXES = ['xhscdn.com', 'xiaohongshu.com'];
const DEFAULT_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36';
const REDIRECT_STATUSES = new Set([301, 302, 303, 307, 308]);

class XhsResolverError extends Error {
  status: number;

  constructor(message: string, status = 502) {
    super(message);
    this.name = 'XhsResolverError';
    this.status = status;
  }
}

function asObject(value: unknown): JsonObject | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as JsonObject
    : null;
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function positiveInteger(value: string | undefined, fallback: number): number {
  const parsed = Number.parseInt(value || '', 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function resolverEndpoint(runtime: XhsResolverRuntime): string | null {
  const raw = runtime.XHS_RESOLVER_URL?.trim();
  if (!raw) return null;

  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    return null;
  }
  if (!['http:', 'https:'].includes(parsed.protocol)) return null;
  if (parsed.username || parsed.password) return null;

  const normalized = parsed.toString().replace(/\/$/, '');
  return normalized.endsWith('/xhs/detail')
    ? normalized
    : `${normalized}/xhs/detail`;
}

export function xhsResolverConfigured(runtime: XhsResolverRuntime): boolean {
  return resolverEndpoint(runtime) !== null;
}

export function xhsResolverMode(runtime: XhsResolverRuntime): 'fallback' | 'prefer' {
  return runtime.XHS_RESOLVER_MODE?.trim().toLowerCase() === 'prefer'
    ? 'prefer'
    : 'fallback';
}

export function isXhsSourceUrl(value: string | null | undefined): boolean {
  if (!value) return false;
  try {
    const host = new URL(value).hostname.toLowerCase().replace(/\.$/, '');
    return host === 'xiaohongshu.com'
      || host.endsWith('.xiaohongshu.com')
      || host === 'xhslink.com'
      || host.endsWith('.xhslink.com');
  } catch {
    return false;
  }
}

function mediaHostSuffixes(runtime: XhsResolverRuntime): string[] {
  const configured = runtime.XHS_MEDIA_HOST_SUFFIXES
    ?.split(',')
    .map((value) => value.trim().toLowerCase().replace(/^\.+/, '').replace(/\.$/, ''))
    .filter(Boolean);
  return configured?.length ? configured : DEFAULT_MEDIA_HOST_SUFFIXES;
}

function hostMatchesSuffix(host: string, suffix: string): boolean {
  return host === suffix || host.endsWith(`.${suffix}`);
}

export function isAllowedXhsMediaUrl(value: string, runtime: XhsResolverRuntime = {}): boolean {
  try {
    const parsed = new URL(value);
    if (!['http:', 'https:'].includes(parsed.protocol)) return false;
    if (parsed.username || parsed.password) return false;
    const host = parsed.hostname.toLowerCase().replace(/\.$/, '');
    if (!host || host === 'localhost' || host.endsWith('.local')) return false;
    if (/^(?:127\.|10\.|192\.168\.|169\.254\.)/.test(host)) return false;
    if (/^172\.(?:1[6-9]|2\d|3[01])\./.test(host)) return false;
    if (host === '::1' || host.startsWith('fc') || host.startsWith('fd') || host.startsWith('fe80:')) return false;
    return mediaHostSuffixes(runtime).some((suffix) => hostMatchesSuffix(host, suffix));
  } catch {
    return false;
  }
}

function parseMedia(detail: JsonObject): XhsMediaItem[] {
  const rawMedia = Array.isArray(detail['媒体']) ? detail['媒体'] : [];
  const output: XhsMediaItem[] = [];

  for (const [position, rawItem] of rawMedia.entries()) {
    const item = asObject(rawItem);
    if (!item) continue;
    const url = stringValue(item['地址']);
    const kind = stringValue(item['类型']);
    if (!url || !kind) continue;

    const rawIndex = typeof item['序号'] === 'number' ? item['序号'] : Number(item['序号']);
    const index = Number.isFinite(rawIndex) && rawIndex > 0 ? Math.trunc(rawIndex) : position + 1;
    const rawSuffix = stringValue(item['扩展名']).toLowerCase().replace(/^\./, '');
    const suffix = /^[a-z0-9]{2,8}$/.test(rawSuffix) ? rawSuffix : (kind === '视频' ? 'mp4' : 'jpg');

    output.push({
      index,
      kind,
      url,
      suffix,
      previewUrl: stringValue(item['预览地址']) || null,
    });
  }

  return output;
}

async function readResolverJson(response: Response): Promise<JsonObject> {
  const text = await response.text();
  if (text.length > MAX_RESOLVER_RESPONSE_CHARS) {
    throw new XhsResolverError('XHS resolver returned an unexpectedly large response');
  }
  let payload: unknown;
  try {
    payload = JSON.parse(text);
  } catch {
    throw new XhsResolverError('XHS resolver returned invalid JSON');
  }
  const object = asObject(payload);
  if (!object) throw new XhsResolverError('XHS resolver returned an invalid payload');
  return object;
}

export async function fetchXhsDetail(sourceUrl: string, runtime: XhsResolverRuntime): Promise<JsonObject> {
  const endpoint = resolverEndpoint(runtime);
  if (!endpoint) throw new XhsResolverError('XHS resolver is not configured', 503);

  const controller = new AbortController();
  const timeout = setTimeout(
    () => controller.abort(),
    positiveInteger(runtime.XHS_RESOLVER_TIMEOUT_MS, DEFAULT_TIMEOUT_MS),
  );

  const headers = new Headers({
    Accept: 'application/json',
    'Content-Type': 'application/json',
  });
  const token = runtime.XHS_RESOLVER_TOKEN?.trim();
  if (token) headers.set('Authorization', `Bearer ${token}`);

  try {
    const response = await fetch(endpoint, {
      method: 'POST',
      headers,
      body: JSON.stringify({ url: sourceUrl, download: false }),
      signal: controller.signal,
      redirect: 'error',
    });
    const payload = await readResolverJson(response);
    if (!response.ok) {
      const message = stringValue(payload.message) || stringValue(payload.error) || `HTTP ${response.status}`;
      throw new XhsResolverError(`XHS resolver failed: ${message}`, response.status >= 500 ? 502 : response.status);
    }
    const detail = asObject(payload.data);
    if (!detail) throw new XhsResolverError('XHS resolver did not return work detail');
    return detail;
  } catch (error) {
    if (error instanceof XhsResolverError) throw error;
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new XhsResolverError('XHS resolver timed out', 504);
    }
    throw new XhsResolverError(`XHS resolver request failed: ${error instanceof Error ? error.message : String(error)}`);
  } finally {
    clearTimeout(timeout);
  }
}

function sourceDownloadUrl(origin: string, sourceUrl: string, mediaType: 'video' | 'audio'): string {
  const output = new URL('/api/download', origin);
  output.searchParams.set('url', sourceUrl);
  output.searchParams.set('type', mediaType);
  output.searchParams.set('quality', 'best');
  return output.toString();
}

export function normalizeXhsDetail(detail: JsonObject, sourceUrl: string, origin: string): JsonObject {
  const media = parseMedia(detail);
  const videos = media.filter((item) => item.kind === '视频');
  const images = media.filter((item) => item.kind === '图片' || item.kind === '动态图片');
  const firstVideo = videos[0] || null;
  const firstImage = images[0] || null;

  if (!firstVideo && images.length === 0) {
    throw new XhsResolverError('XHS resolver returned no downloadable media', 404);
  }

  const title = stringValue(detail['作品标题']) || 'Xiaohongshu media';
  const description = stringValue(detail['作品描述']);
  const cover = firstVideo?.previewUrl || firstImage?.url || null;
  const author = asObject(detail['作者']);
  const authorName = author ? stringValue(author['作者昵称']) : '';
  const videoDownloadUrl = firstVideo ? sourceDownloadUrl(origin, sourceUrl, 'video') : null;

  const common: JsonObject = {
    title,
    desc: description,
    cover,
    platform: 'xiaohongshu',
    url: sourceUrl,
    duration: undefined,
    author: authorName || undefined,
    originDownloadAudioUrl: null,
    subtitles: [],
  };

  if (firstVideo && (stringValue(detail['作品类型']) === '视频' || images.length === 0)) {
    return {
      ...common,
      downloadAudioUrl: null,
      downloadVideoUrl: videoDownloadUrl,
      originDownloadVideoUrl: null,
      videoAudioMode: 'muxed',
      mediaActions: {
        video: 'direct-download',
        audio: 'extract-audio',
      },
      qualityOptions: [{
        quality: 'best',
        label: `Original · ${firstVideo.suffix.toUpperCase()}`,
        ext: firstVideo.suffix,
        downloadUrl: videoDownloadUrl,
      }],
      noteType: 'video',
      kind: 'video',
      images: [],
    };
  }

  return {
    ...common,
    downloadAudioUrl: null,
    downloadVideoUrl: null,
    originDownloadVideoUrl: null,
    videoAudioMode: 'not_applicable',
    mediaActions: {
      video: 'hide',
      audio: 'hide',
    },
    qualityOptions: [],
    noteType: 'image',
    kind: 'image',
    images: images.map((item) => ({
      index: item.index,
      url: item.url,
      downloadUrl: item.url,
    })),
  };
}

export async function xhsParseResponse(
  request: Request,
  sourceUrl: string,
  runtime: XhsResolverRuntime,
  requestId: string,
): Promise<Response> {
  try {
    const detail = await fetchXhsDetail(sourceUrl, runtime);
    const data = normalizeXhsDetail(detail, sourceUrl, new URL(request.url).origin);
    return Response.json(
      { success: true, data, requestId, details: { provider: 'xhs-resolver' } },
      { headers: { 'X-Request-Id': requestId } },
    );
  } catch (error) {
    const status = error instanceof XhsResolverError ? error.status : 502;
    return Response.json(
      {
        success: false,
        code: 'PARSE_FAILED',
        status,
        error: error instanceof Error ? error.message : String(error),
        requestId,
        details: { provider: 'xhs-resolver' },
      },
      { status, headers: { 'X-Request-Id': requestId } },
    );
  }
}

function maxStreamBytes(runtime: XhsResolverRuntime): number {
  return positiveInteger(runtime.XHS_MAX_STREAM_BYTES, DEFAULT_MAX_STREAM_BYTES);
}

async function fetchXhsMedia(
  mediaUrl: string,
  sourceUrl: string,
  request: Request,
  runtime: XhsResolverRuntime,
): Promise<Response> {
  let currentUrl = mediaUrl;
  const userAgent = runtime.YTDLP_USER_AGENT?.trim() || DEFAULT_USER_AGENT;

  for (let redirect = 0; redirect <= 4; redirect += 1) {
    if (!isAllowedXhsMediaUrl(currentUrl, runtime)) {
      throw new XhsResolverError('XHS resolver returned a media host that is not allowlisted', 502);
    }

    const headers = new Headers({
      Accept: '*/*',
      Referer: sourceUrl,
      'User-Agent': userAgent,
    });
    const range = request.headers.get('range');
    if (range) headers.set('Range', range);

    const response = await fetch(currentUrl, {
      method: 'GET',
      headers,
      redirect: 'manual',
    });

    if (!REDIRECT_STATUSES.has(response.status)) return response;
    const location = response.headers.get('location');
    void response.body?.cancel();
    if (!location) throw new XhsResolverError('XHS media redirect did not include a location');
    currentUrl = new URL(location, currentUrl).toString();
  }

  throw new XhsResolverError('XHS media exceeded the redirect limit');
}

export async function xhsDownloadResponse(
  request: Request,
  sourceUrl: string,
  runtime: XhsResolverRuntime,
  requestId: string,
): Promise<Response | null> {
  const url = new URL(request.url);
  const mediaType = (url.searchParams.get('type') || 'video').toLowerCase();
  if (mediaType !== 'video') return null;

  if (request.method === 'HEAD') {
    return Response.json(
      { success: true, ready: true, requestId, details: { provider: 'xhs-resolver' } },
      { headers: { 'X-Request-Id': requestId } },
    );
  }

  try {
    const detail = await fetchXhsDetail(sourceUrl, runtime);
    const video = parseMedia(detail).find((item) => item.kind === '视频');
    if (!video) throw new XhsResolverError('XHS work does not contain a video', 404);

    const upstream = await fetchXhsMedia(video.url, sourceUrl, request, runtime);
    if (!upstream.ok && upstream.status !== 206) {
      const status = upstream.status;
      void upstream.body?.cancel();
      throw new XhsResolverError(`XHS media upstream returned HTTP ${status}`, 502);
    }

    const contentLength = Number.parseInt(upstream.headers.get('content-length') || '', 10);
    if (Number.isFinite(contentLength) && contentLength > maxStreamBytes(runtime)) {
      void upstream.body?.cancel();
      throw new XhsResolverError(`XHS media exceeds the ${maxStreamBytes(runtime)} byte stream limit`, 413);
    }

    const headers = new Headers();
    for (const name of ['content-type', 'content-length', 'content-range', 'accept-ranges', 'etag', 'last-modified']) {
      const value = upstream.headers.get(name);
      if (value) headers.set(name, value);
    }
    if (!headers.has('content-type')) headers.set('Content-Type', video.suffix === 'mp4' ? 'video/mp4' : 'application/octet-stream');
    headers.set('Content-Disposition', `attachment; filename="xiaohongshu.${video.suffix}"`);
    headers.set('Cache-Control', 'private, no-store');
    headers.set('X-Request-Id', requestId);
    headers.set('X-Galaxy-Provider', 'xhs-resolver');

    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers,
    });
  } catch (error) {
    const status = error instanceof XhsResolverError ? error.status : 502;
    return Response.json(
      {
        success: false,
        code: 'UPSTREAM_ERROR',
        status,
        error: error instanceof Error ? error.message : String(error),
        requestId,
        details: { provider: 'xhs-resolver' },
      },
      { status, headers: { 'X-Request-Id': requestId } },
    );
  }
}
