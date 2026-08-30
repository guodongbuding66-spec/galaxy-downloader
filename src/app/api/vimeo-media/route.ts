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

function failure(message: string, status = 502) {
    const response = NextResponse.json({
        success: false,
        code: status === 400 ? 'BAD_REQUEST' : 'UPSTREAM_ERROR',
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
    if (!response.ok) throw new Error(`Vimeo metadata returned ${response.status}`);
    return response.json() as Promise<T>;
}

async function getEmbedUrl(id: string): Promise<string> {
    const oembed = new URL('https://vimeo.com/api/oembed.json');
    oembed.searchParams.set('url', `https://vimeo.com/${id}`);
    const payload = await fetchJson<VimeoOEmbed>(oembed.toString(), {
        ...JSON_HEADERS,
        Referer: 'https://vimeo.com/',
    });
    const src = payload.html?.match(/<iframe[^>]+src=["']([^"']+)["']/i)?.[1];
    if (!src) throw new Error('Vimeo oEmbed did not return an iframe URL');
    const embed = new URL(decodeHtml(src));
    if (embed.hostname !== 'player.vimeo.com' || !embed.pathname.startsWith(`/video/${id}`)) {
        throw new Error('Unexpected Vimeo embed URL');
    }
    return embed.toString();
}

async function fetchConfig(id: string): Promise<{ config: VimeoConfig; embedUrl: string }> {
    const embedUrl = await getEmbedUrl(id);
    const page = await fetch(embedUrl, {
        headers: { ...HTML_HEADERS, Referer: `https://vimeo.com/${id}` },
        redirect: 'follow',
        cache: 'no-store',
    });
    if (page.ok) {
        const html = await page.text();
        for (const marker of [/\bplayerConfig\s*=\s*/i, /\bvimeo\.config\s*=\s*/i, /\bconfig\s*=\s*/i]) {
            const value = extractBalancedJson(html, marker);
            if (value && typeof value === 'object') return { config: value as VimeoConfig, embedUrl };
        }
        const configValue = html.match(/\bdata-config-url=["']([^"']+)["']/i)?.[1]
            || html.match(/["']config_url["']\s*:\s*["']([^"']+)["']/i)?.[1];
        if (configValue) {
            const config = await fetchJson<VimeoConfig>(decodeHtml(configValue), {
                ...JSON_HEADERS,
                Referer: embedUrl,
                Origin: 'https://player.vimeo.com',
            });
            return { config, embedUrl };
        }
    }
    const configUrl = new URL(embedUrl);
    configUrl.pathname = `${configUrl.pathname.replace(/\/$/, '')}/config`;
    const config = await fetchJson<VimeoConfig>(configUrl.toString(), {
        ...JSON_HEADERS,
        Referer: embedUrl,
        Origin: 'https://player.vimeo.com',
    });
    return { config, embedUrl };
}

function selectProgressive(config: VimeoConfig, quality: string): VimeoProgressive | null {
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

function copyHeader(from: Headers, to: Headers, name: string) {
    const value = from.get(name);
    if (value) to.set(name, value);
}

async function handle(request: NextRequest, headOnly: boolean) {
    const id = request.nextUrl.searchParams.get('id')?.trim() || '';
    if (!/^\d{5,}$/.test(id)) return failure('Invalid Vimeo id', 400);
    const quality = request.nextUrl.searchParams.get('quality')?.trim() || 'best';

    let selected: VimeoProgressive | null;
    let embedUrl: string;
    try {
        const resolved = await fetchConfig(id);
        selected = selectProgressive(resolved.config, quality);
        embedUrl = resolved.embedUrl;
    } catch (error) {
        return failure(error instanceof Error ? error.message : 'Unable to resolve Vimeo media');
    }
    if (!selected?.url) return failure('Vimeo progressive media not available');

    const headers = new Headers({
        Accept: '*/*',
        'User-Agent': USER_AGENT,
        Referer: embedUrl,
        Origin: 'https://player.vimeo.com',
    });
    const range = request.headers.get('range');
    if (range) headers.set('Range', range);

    let upstream: Response;
    try {
        upstream = await fetch(selected.url, {
            method: 'GET',
            headers,
            redirect: 'follow',
            cache: 'no-store',
        });
    } catch {
        return failure('Unable to fetch Vimeo media');
    }
    if (!upstream.ok || !upstream.body) {
        void upstream.body?.cancel();
        return failure(`Vimeo media returned ${upstream.status}`);
    }

    const responseHeaders = new Headers();
    for (const name of ['content-type', 'content-length', 'content-range', 'accept-ranges', 'etag', 'last-modified']) {
        copyHeader(upstream.headers, responseHeaders, name);
    }
    responseHeaders.set('Cache-Control', 'private, no-store');
    responseHeaders.set('Content-Disposition', `attachment; filename="vimeo-${id}.mp4"`);
    responseHeaders.set('Cross-Origin-Resource-Policy', 'same-origin');
    responseHeaders.set('X-Robots-Tag', 'noindex, nofollow, noarchive');

    if (headOnly) {
        void upstream.body.cancel();
        return new NextResponse(null, { status: upstream.status, headers: responseHeaders });
    }
    return new NextResponse(upstream.body, { status: upstream.status, headers: responseHeaders });
}

export async function GET(request: NextRequest) {
    return handle(request, false);
}

export async function HEAD(request: NextRequest) {
    return handle(request, true);
}
