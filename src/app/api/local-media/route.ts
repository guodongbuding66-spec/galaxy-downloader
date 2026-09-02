import { NextRequest, NextResponse } from 'next/server';

const USER_AGENT =
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36';

const JSON_HEADERS = {
    Accept: 'application/json,text/plain,*/*',
    'Accept-Language': 'en-US,en;q=0.9',
    'User-Agent': USER_AGENT,
};

const HTML_HEADERS = {
    Accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'User-Agent': USER_AGENT,
};

const DAILYMOTION_MEDIA_HOSTS = [
    'dmcdn.net',
    'dailymotion.com',
    'dailymotioncdn.com',
];
const DAILYMOTION_HLS_ATTEMPTS = 3;
const DAILYMOTION_BLOCKBUSTER_ALPHABET = 'bcdfghjklmnpqrstvwxyz';
const VIMEO_CONTROL_TIMEOUT_MS = 5_500;
const VIMEO_CONTROL_ATTEMPTS = 2;

type VimeoProgressive = {
    url?: string;
    quality?: string;
    height?: number;
};

type VimeoConfig = {
    video?: { files?: { progressive?: VimeoProgressive[] } };
    request?: { files?: { progressive?: VimeoProgressive[] } };
};

type VimeoOEmbed = { html?: string };

type DailymotionSource = {
    type?: string;
    url?: string;
};

type DailymotionMetadata = {
    qualities?: Record<string, DailymotionSource[]>;
};

type AppleLookupItem = {
    wrapperType?: string;
    kind?: string;
    trackId?: number;
    episodeUrl?: string;
};

type AppleLookupPayload = {
    results?: AppleLookupItem[];
};

type ResolvedMedia = {
    url: string;
    referer?: string;
    origin?: string;
    filename: string;
};

function failure(message: string, status: number) {
    const response = NextResponse.json({
        success: false,
        code: status === 400 || status === 403 ? 'BAD_REQUEST' : 'UPSTREAM_ERROR',
        status,
        error: message,
    }, { status });
    response.headers.set('Cache-Control', 'no-store');
    response.headers.set('X-Robots-Tag', 'noindex, nofollow, noarchive');
    return response;
}

function decodeHtml(value: string): string {
    return value
        .replace(/&amp;/g, '&')
        .replace(/&quot;/g, '"')
        .replace(/&#39;/g, "'")
        .replace(/\\u0026/gi, '&')
        .replace(/\\\//g, '/');
}

function extractBalancedJson(text: string, marker: RegExp): unknown | null {
    const match = marker.exec(text);
    if (!match) return null;
    const start = text.indexOf('{', match.index + match[0].length);
    if (start < 0) return null;

    let depth = 0;
    let inString = false;
    let escaped = false;
    for (let index = start; index < text.length; index += 1) {
        const char = text[index];
        if (inString) {
            if (escaped) escaped = false;
            else if (char === '\\') escaped = true;
            else if (char === '"') inString = false;
            continue;
        }
        if (char === '"') {
            inString = true;
            continue;
        }
        if (char === '{') depth += 1;
        else if (char === '}') {
            depth -= 1;
            if (depth === 0) {
                try {
                    return JSON.parse(text.slice(start, index + 1));
                } catch {
                    return null;
                }
            }
        }
    }
    return null;
}

async function fetchJson<T>(url: string, headers: HeadersInit = JSON_HEADERS): Promise<T> {
    const response = await fetch(url, { headers, redirect: 'follow', cache: 'no-store' });
    if (!response.ok) throw new Error(`Metadata request failed (${response.status})`);
    return response.json() as Promise<T>;
}

function isRetryableControlStatus(status: number): boolean {
    return status === 408 || status === 429 || status >= 500;
}

async function runVimeoControlRequest<T>(label: string, operation: (signal: AbortSignal) => Promise<T>): Promise<T> {
    let lastError: unknown = null;
    for (let attempt = 1; attempt <= VIMEO_CONTROL_ATTEMPTS; attempt += 1) {
        try {
            return await operation(AbortSignal.timeout(VIMEO_CONTROL_TIMEOUT_MS));
        } catch (error) {
            lastError = error;
            if (attempt >= VIMEO_CONTROL_ATTEMPTS) break;
            await new Promise((resolve) => setTimeout(resolve, 150 * attempt));
        }
    }
    const detail = lastError instanceof Error ? lastError.message : String(lastError || 'unknown error');
    throw new Error(`${label} failed after ${VIMEO_CONTROL_ATTEMPTS} attempts: ${detail}`);
}

async function fetchVimeoJson<T>(url: string, headers: HeadersInit): Promise<T> {
    return runVimeoControlRequest('Vimeo JSON request', async (signal) => {
        const response = await fetch(url, {
            headers,
            redirect: 'follow',
            cache: 'no-store',
            signal,
        });
        if (!response.ok) {
            if (isRetryableControlStatus(response.status)) {
                void response.body?.cancel();
                throw new Error(`retryable HTTP ${response.status}`);
            }
            throw new Error(`HTTP ${response.status}`);
        }
        return response.json() as Promise<T>;
    });
}

async function fetchVimeoPage(url: string, headers: HeadersInit): Promise<{ ok: boolean; status: number; text: string }> {
    return runVimeoControlRequest('Vimeo player request', async (signal) => {
        const response = await fetch(url, {
            headers,
            redirect: 'follow',
            cache: 'no-store',
            signal,
        });
        if (!response.ok && isRetryableControlStatus(response.status)) {
            void response.body?.cancel();
            throw new Error(`retryable HTTP ${response.status}`);
        }
        const text = response.ok ? await response.text() : '';
        return { ok: response.ok, status: response.status, text };
    });
}

function requestedQuality(request: NextRequest): string {
    return request.nextUrl.searchParams.get('quality')?.trim() || 'best';
}

function iframeSrc(html: string | undefined): string | null {
    if (!html) return null;
    const value = html.match(/<iframe[^>]+src=["']([^"']+)["']/i)?.[1];
    return value ? decodeHtml(value) : null;
}

async function getVimeoEmbedUrl(id: string): Promise<string> {
    const endpoint = new URL('https://vimeo.com/api/oembed.json');
    endpoint.searchParams.set('url', `https://vimeo.com/${id}`);
    const payload = await fetchVimeoJson<VimeoOEmbed>(endpoint.toString(), {
        ...JSON_HEADERS,
        Referer: 'https://vimeo.com/',
    });
    const src = iframeSrc(payload.html);
    if (!src) throw new Error('Vimeo oEmbed did not return an iframe URL');
    const embed = new URL(src);
    if (embed.hostname !== 'player.vimeo.com' || !embed.pathname.startsWith(`/video/${id}`)) {
        throw new Error('Unexpected Vimeo embed URL');
    }
    return embed.toString();
}

async function fetchVimeoConfig(id: string): Promise<{ config: VimeoConfig; embedUrl: string }> {
    const embedUrl = await getVimeoEmbedUrl(id);
    const page = await fetchVimeoPage(embedUrl, {
        ...HTML_HEADERS,
        Referer: `https://vimeo.com/${id}`,
    });

    if (page.ok) {
        const html = page.text;
        for (const marker of [/\bplayerConfig\s*=\s*/i, /\bvimeo\.config\s*=\s*/i, /\bconfig\s*=\s*/i]) {
            const value = extractBalancedJson(html, marker);
            if (value && typeof value === 'object') return { config: value as VimeoConfig, embedUrl };
        }
        const configValue = html.match(/\bdata-config-url=["']([^"']+)["']/i)?.[1]
            || html.match(/["']config_url["']\s*:\s*["']([^"']+)["']/i)?.[1];
        if (configValue) {
            const config = await fetchVimeoJson<VimeoConfig>(decodeHtml(configValue), {
                ...JSON_HEADERS,
                Referer: embedUrl,
                Origin: 'https://player.vimeo.com',
            });
            return { config, embedUrl };
        }
    }

    const configUrl = new URL(embedUrl);
    configUrl.pathname = `${configUrl.pathname.replace(/\/$/, '')}/config`;
    const config = await fetchVimeoJson<VimeoConfig>(configUrl.toString(), {
        ...JSON_HEADERS,
        Referer: embedUrl,
        Origin: 'https://player.vimeo.com',
    });
    return { config, embedUrl };
}

function pickVimeoProgressive(config: VimeoConfig, quality: string): VimeoProgressive | null {
    const formats = (config.video?.files?.progressive || config.request?.files?.progressive || [])
        .filter((item) => typeof item.url === 'string' && item.url.length > 0)
        .sort((a, b) => (b.height || 0) - (a.height || 0));
    if (!formats.length) return null;
    if (quality === 'best') return formats[0];
    const height = Number.parseInt(quality, 10);
    if (Number.isFinite(height)) {
        return formats.find((item) => item.height === height)
            || formats.find((item) => (item.height || 0) <= height)
            || formats[formats.length - 1];
    }
    return formats.find((item) => item.quality === quality) || formats[0];
}

async function resolveVimeo(request: NextRequest): Promise<ResolvedMedia> {
    const id = request.nextUrl.searchParams.get('id')?.trim();
    if (!id || !/^\d{5,}$/.test(id)) throw new Error('Invalid Vimeo id');
    const { config, embedUrl } = await fetchVimeoConfig(id);
    const selected = pickVimeoProgressive(config, requestedQuality(request));
    if (!selected?.url) throw new Error('Vimeo progressive stream not available');
    return {
        url: selected.url,
        referer: embedUrl,
        origin: 'https://player.vimeo.com',
        filename: `vimeo-${id}.mp4`,
    };
}

function dailymotionMetadataUrl(id: string): string {
    const url = new URL(`https://www.dailymotion.com/player/metadata/video/${encodeURIComponent(id)}`);
    url.searchParams.set('app', 'com.dailymotion.neon');
    return url.toString();
}

async function fetchDailymotionMetadata(id: string): Promise<DailymotionMetadata> {
    return fetchJson<DailymotionMetadata>(dailymotionMetadataUrl(id));
}

function dailymotionMp4Formats(metadata: DailymotionMetadata): Array<{ quality: string; url: string }> {
    const formats: Array<{ quality: string; url: string }> = [];
    for (const [quality, sources] of Object.entries(metadata.qualities || {})) {
        if (!Array.isArray(sources)) continue;
        const source = sources.find((item) =>
            typeof item?.url === 'string'
            && item.url.length > 0
            && (item.type?.includes('mp4') || item.url.includes('.mp4'))
        );
        if (source?.url) formats.push({ quality, url: source.url });
    }
    return formats.sort((a, b) => Number.parseInt(b.quality, 10) - Number.parseInt(a.quality, 10));
}

function dailymotionMasterHls(metadata: DailymotionMetadata): URL | null {
    for (const sources of Object.values(metadata.qualities || {})) {
        if (!Array.isArray(sources)) continue;
        const source = sources.find((item) =>
            typeof item?.url === 'string'
            && item.url.length > 0
            && (item.type?.toLowerCase().includes('mpegurl') || item.url.includes('.m3u8'))
        );
        if (source?.url) return safeDailymotionTarget(source.url.split('#')[0]);
    }
    return null;
}

async function resolveDailymotion(request: NextRequest): Promise<ResolvedMedia> {
    const id = request.nextUrl.searchParams.get('id')?.trim();
    if (!id || !/^[a-zA-Z0-9]+$/.test(id)) throw new Error('Invalid Dailymotion id');
    const metadata = await fetchDailymotionMetadata(id);
    const formats = dailymotionMp4Formats(metadata);
    if (!formats.length) throw new Error('Dailymotion progressive stream not available');
    const quality = requestedQuality(request);
    const target = quality === 'best'
        ? formats[0]
        : formats.find((item) => item.quality === quality) || formats[0];
    return {
        url: target.url,
        referer: `https://www.dailymotion.com/video/${id}`,
        filename: `dailymotion-${id}.mp4`,
    };
}

function allowedDailymotionHost(hostname: string): boolean {
    const host = hostname.toLowerCase();
    return DAILYMOTION_MEDIA_HOSTS.some((allowed) => host === allowed || host.endsWith(`.${allowed}`));
}

function safeDailymotionTarget(raw: string): URL | null {
    try {
        const url = new URL(raw);
        if (url.protocol !== 'https:' || !allowedDailymotionHost(url.hostname)) return null;
        return url;
    } catch {
        return null;
    }
}

function dailymotionRelayUrl(request: NextRequest, id: string, target: string): string {
    const url = new URL('/api/local-media', request.nextUrl.origin);
    url.searchParams.set('platform', 'dailymotion');
    url.searchParams.set('mode', 'hls');
    url.searchParams.set('id', id);
    url.searchParams.set('target', target);
    return `${url.pathname}?${url.searchParams.toString()}`;
}

function rewriteDailymotionUri(base: URL, raw: string, request: NextRequest, id: string): string {
    try {
        const target = new URL(raw, base);
        if (target.protocol !== 'https:' || !allowedDailymotionHost(target.hostname)) return raw;
        return dailymotionRelayUrl(request, id, target.toString());
    } catch {
        return raw;
    }
}

function rewriteDailymotionPlaylist(text: string, base: URL, request: NextRequest, id: string): string {
    return text
        .split(/\r?\n/)
        .map((line) => {
            const trimmed = line.trim();
            if (!trimmed) return line;
            if (!trimmed.startsWith('#')) return rewriteDailymotionUri(base, trimmed, request, id);
            return line.replace(/URI="([^"]+)"/g, (_match, uri: string) =>
                `URI="${rewriteDailymotionUri(base, uri, request, id)}"`
            );
        })
        .join('\n');
}

function isHlsPlaylist(target: URL, response: Response): boolean {
    const contentType = response.headers.get('content-type')?.toLowerCase() || '';
    return target.pathname.toLowerCase().endsWith('.m3u8')
        || contentType.includes('mpegurl')
        || contentType.includes('vnd.apple.mpegurl');
}

function copyHeader(from: Headers, to: Headers, name: string) {
    const value = from.get(name);
    if (value) to.set(name, value);
}

function randomDailymotionLetters(minimum: number, maximum: number): string {
    const length = minimum + Math.floor(Math.random() * (maximum - minimum + 1));
    let value = '';
    for (let index = 0; index < length; index += 1) {
        value += DAILYMOTION_BLOCKBUSTER_ALPHABET[
            Math.floor(Math.random() * DAILYMOTION_BLOCKBUSTER_ALPHABET.length)
        ];
    }
    return value;
}

function dailymotionBlockbusterHeaders(id: string, target: URL, range: string | null, attempt: number): Headers {
    const headers = new Headers({
        Accept: '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'User-Agent': USER_AGENT,
    });

    // Dailymotion has used HTTP-header fingerprint blocking on HLS manifests.
    // yt-dlp works around this by randomizing otherwise meaningless header names.
    // Keep the same concept here while never forwarding user-controlled headers.
    const randomHeaderCount = 2 + Math.floor(Math.random() * 7);
    for (let index = 0; index < randomHeaderCount; index += 1) {
        headers.set(randomDailymotionLetters(8, 16), randomDailymotionLetters(8, 24));
    }

    if (attempt === 1) {
        headers.set('Referer', `https://www.dailymotion.com/video/${id}`);
        headers.set('Origin', 'https://www.dailymotion.com');
    } else if (attempt >= 2) {
        headers.set('Referer', 'https://www.dailymotion.com/');
        headers.set('Origin', 'https://www.dailymotion.com');
    }

    if (range && !target.pathname.toLowerCase().endsWith('.m3u8')) {
        headers.set('Range', range);
    }
    return headers;
}

function retryableDailymotionStatus(status: number): boolean {
    return status === 403 || status === 408 || status === 429 || status >= 500;
}

async function fetchDailymotionHlsResource(
    target: URL,
    id: string,
    range: string | null,
): Promise<Response> {
    let lastResponse: Response | null = null;
    let lastError: unknown = null;

    for (let attempt = 0; attempt < DAILYMOTION_HLS_ATTEMPTS; attempt += 1) {
        try {
            const upstream = await fetch(target.toString(), {
                method: 'GET',
                headers: dailymotionBlockbusterHeaders(id, target, range, attempt),
                redirect: 'follow',
                cache: 'no-store',
            });
            lastResponse = upstream;
            if (!retryableDailymotionStatus(upstream.status) || attempt === DAILYMOTION_HLS_ATTEMPTS - 1) {
                return upstream;
            }
            void upstream.body?.cancel();
        } catch (error) {
            lastError = error;
            if (attempt === DAILYMOTION_HLS_ATTEMPTS - 1) break;
        }
        await new Promise((resolve) => setTimeout(resolve, 100 * (attempt + 1)));
    }

    if (lastResponse) return lastResponse;
    const detail = lastError instanceof Error ? lastError.message : String(lastError || 'unknown error');
    throw new Error(`Dailymotion HLS fetch failed after ${DAILYMOTION_HLS_ATTEMPTS} attempts: ${detail}`);
}

async function handleDailymotionHls(request: NextRequest, headOnly: boolean) {
    const id = request.nextUrl.searchParams.get('id')?.trim() || '';
    if (!/^[a-zA-Z0-9]+$/.test(id)) return failure('Invalid Dailymotion id', 400);

    let target: URL | null = null;
    const requestedTarget = request.nextUrl.searchParams.get('target')?.trim();
    if (requestedTarget) {
        target = safeDailymotionTarget(requestedTarget);
        if (!target) return failure('Dailymotion relay target is not allowed', 403);
    } else {
        try {
            target = dailymotionMasterHls(await fetchDailymotionMetadata(id));
        } catch (error) {
            return failure(error instanceof Error ? error.message : 'Unable to resolve Dailymotion HLS', 502);
        }
        if (!target) return failure('Dailymotion HLS stream not available', 502);
    }

    const range = request.headers.get('range');
    let upstream: Response;
    try {
        upstream = await fetchDailymotionHlsResource(target, id, range);
    } catch (error) {
        const detail = error instanceof Error ? error.message : 'Unable to fetch Dailymotion HLS resource';
        return failure(detail, 502);
    }

    if (!upstream.ok || !upstream.body) {
        void upstream.body?.cancel();
        return failure(`Dailymotion HLS resource returned ${upstream.status}`, 502);
    }

    const responseHeaders = new Headers();
    responseHeaders.set('Cache-Control', 'private, no-store');
    responseHeaders.set('Cross-Origin-Resource-Policy', 'same-origin');
    responseHeaders.set('X-Robots-Tag', 'noindex, nofollow, noarchive');

    if (isHlsPlaylist(target, upstream)) {
        if (headOnly) {
            void upstream.body.cancel();
            responseHeaders.set('Content-Type', 'application/vnd.apple.mpegurl; charset=utf-8');
            return new NextResponse(null, { status: 200, headers: responseHeaders });
        }
        const text = await upstream.text();
        const rewritten = rewriteDailymotionPlaylist(text, target, request, id);
        responseHeaders.set('Content-Type', 'application/vnd.apple.mpegurl; charset=utf-8');
        responseHeaders.set('Content-Length', String(new TextEncoder().encode(rewritten).byteLength));
        return new NextResponse(rewritten, { status: 200, headers: responseHeaders });
    }

    for (const name of ['content-type', 'content-length', 'content-range', 'accept-ranges', 'etag', 'last-modified']) {
        copyHeader(upstream.headers, responseHeaders, name);
    }
    if (headOnly) {
        void upstream.body.cancel();
        return new NextResponse(null, { status: upstream.status, headers: responseHeaders });
    }
    return new NextResponse(upstream.body, { status: upstream.status, headers: responseHeaders });
}

function findFirstStringForKey(value: unknown, key: string): string | null {
    if (!value || typeof value !== 'object') return null;
    if (Array.isArray(value)) {
        for (const item of value) {
            const found = findFirstStringForKey(item, key);
            if (found) return found;
        }
        return null;
    }
    const record = value as Record<string, unknown>;
    const direct = record[key];
    if (typeof direct === 'string' && direct.startsWith('http')) return direct;
    for (const child of Object.values(record)) {
        const found = findFirstStringForKey(child, key);
        if (found) return found;
    }
    return null;
}

async function streamUrlFromApplePage(sourceUrl: string): Promise<string | null> {
    const response = await fetch(sourceUrl, { headers: HTML_HEADERS, redirect: 'follow', cache: 'no-store' });
    if (!response.ok) return null;
    const html = await response.text();
    const scriptMatch = html.match(/<script[^>]+id=["']serialized-server-data["'][^>]*>([\s\S]*?)<\/script>/i);
    if (scriptMatch?.[1]) {
        try {
            const payload = JSON.parse(scriptMatch[1]);
            const streamUrl = findFirstStringForKey(payload, 'streamUrl');
            if (streamUrl) return decodeHtml(streamUrl);
        } catch {
            // Fall through to tolerant regex extraction.
        }
    }
    const raw = html.match(/["']streamUrl["']\s*:\s*["']([^"']+)["']/i)?.[1]
        || html.match(/\\"streamUrl\\"\s*:\s*\\"([^"\\]+)\\"/i)?.[1];
    return raw ? decodeHtml(raw) : null;
}

function isAppleEpisode(item: AppleLookupItem): boolean {
    return item.kind === 'podcast-episode'
        || item.wrapperType === 'podcastEpisode'
        || typeof item.episodeUrl === 'string';
}

async function resolveApplePodcast(request: NextRequest): Promise<ResolvedMedia> {
    const source = request.nextUrl.searchParams.get('source')?.trim();
    const episodeId = request.nextUrl.searchParams.get('episodeId')?.trim();
    if (source && episodeId && /^\d+$/.test(episodeId)) {
        const streamUrl = await streamUrlFromApplePage(source);
        if (streamUrl) {
            return {
                url: streamUrl,
                referer: source,
                filename: `apple-podcast-${episodeId}.m4a`,
            };
        }
    }

    const showId = request.nextUrl.searchParams.get('showId')?.trim();
    if (!showId || !/^\d+$/.test(showId) || !episodeId || !/^\d+$/.test(episodeId)) {
        throw new Error('Invalid Apple Podcasts identifiers');
    }
    const lookup = new URL('https://itunes.apple.com/lookup');
    lookup.searchParams.set('id', showId);
    lookup.searchParams.set('entity', 'podcastEpisode');
    lookup.searchParams.set('limit', '200');
    const payload = await fetchJson<AppleLookupPayload>(lookup.toString(), {
        Accept: 'application/json,*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'User-Agent': 'iTunes/12.13.2 (Windows; Microsoft Windows 10 x64) AppleWebKit/7606.3.2.30005.1',
    });
    const episode = (payload.results || []).find((item) =>
        isAppleEpisode(item) && String(item.trackId || '') === episodeId && typeof item.episodeUrl === 'string'
    );
    if (!episode?.episodeUrl) throw new Error('Apple podcast episode media not found');
    return {
        url: episode.episodeUrl,
        filename: `apple-podcast-${episodeId}.mp3`,
    };
}

async function resolveMedia(request: NextRequest): Promise<ResolvedMedia> {
    const platform = request.nextUrl.searchParams.get('platform')?.trim();
    if (platform === 'vimeo') return resolveVimeo(request);
    if (platform === 'dailymotion') return resolveDailymotion(request);
    if (platform === 'apple_podcasts') return resolveApplePodcast(request);
    throw new Error('Unsupported local media platform');
}

async function handleDirectMedia(request: NextRequest, headOnly: boolean) {
    let media: ResolvedMedia;
    try {
        media = await resolveMedia(request);
    } catch (error) {
        return failure(error instanceof Error ? error.message : 'Unable to resolve local media', 400);
    }

    const headers = new Headers({
        Accept: '*/*',
        'User-Agent': USER_AGENT,
    });
    const range = request.headers.get('range');
    if (range) headers.set('Range', range);
    if (media.referer) headers.set('Referer', media.referer);
    if (media.origin) headers.set('Origin', media.origin);

    let upstream: Response;
    try {
        upstream = await fetch(media.url, {
            method: 'GET',
            headers,
            redirect: 'follow',
            cache: 'no-store',
        });
    } catch (error) {
        console.warn('Local media upstream fetch failed', {
            url: media.url,
            error: error instanceof Error ? error.message : String(error),
        });
        return failure('Unable to fetch resolved media', 502);
    }

    if (!upstream.ok || !upstream.body) {
        void upstream.body?.cancel();
        return failure(`Resolved media returned ${upstream.status}`, 502);
    }

    const responseHeaders = new Headers();
    for (const name of ['content-type', 'content-length', 'content-range', 'accept-ranges', 'etag', 'last-modified']) {
        copyHeader(upstream.headers, responseHeaders, name);
    }
    responseHeaders.set('Cache-Control', 'private, no-store');
    responseHeaders.set('Content-Disposition', `attachment; filename="${media.filename}"`);
    responseHeaders.set('Cross-Origin-Resource-Policy', 'same-origin');
    responseHeaders.set('X-Robots-Tag', 'noindex, nofollow, noarchive');

    if (headOnly) {
        void upstream.body.cancel();
        return new NextResponse(null, { status: upstream.status, headers: responseHeaders });
    }
    return new NextResponse(upstream.body, { status: upstream.status, headers: responseHeaders });
}

async function handle(request: NextRequest, headOnly: boolean) {
    const platform = request.nextUrl.searchParams.get('platform')?.trim();
    const mode = request.nextUrl.searchParams.get('mode')?.trim();
    if (platform === 'dailymotion' && mode === 'hls') {
        return handleDailymotionHls(request, headOnly);
    }
    return handleDirectMedia(request, headOnly);
}

export async function GET(request: NextRequest) {
    return handle(request, false);
}

export async function HEAD(request: NextRequest) {
    return handle(request, true);
}
