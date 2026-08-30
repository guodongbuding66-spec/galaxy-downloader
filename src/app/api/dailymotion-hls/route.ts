import { NextRequest, NextResponse } from 'next/server';

const USER_AGENT =
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36';

const JSON_HEADERS = {
    Accept: 'application/json,text/plain,*/*',
    'Accept-Language': 'en-US,en;q=0.9',
    'User-Agent': USER_AGENT,
};

const ALLOWED_MEDIA_HOSTS = [
    'dmcdn.net',
    'dailymotion.com',
    'dailymotioncdn.com',
];

type DailymotionSource = {
    type?: string;
    url?: string;
};

type DailymotionMetadata = {
    qualities?: Record<string, DailymotionSource[]>;
};

function failure(message: string, status = 502) {
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

function allowedHost(hostname: string): boolean {
    const host = hostname.toLowerCase();
    return ALLOWED_MEDIA_HOSTS.some((allowed) => host === allowed || host.endsWith(`.${allowed}`));
}

function safeTarget(raw: string): URL | null {
    try {
        const url = new URL(raw);
        if (url.protocol !== 'https:') return null;
        if (!allowedHost(url.hostname)) return null;
        return url;
    } catch {
        return null;
    }
}

async function metadataFor(id: string): Promise<DailymotionMetadata> {
    const response = await fetch(`https://www.dailymotion.com/player/metadata/video/${encodeURIComponent(id)}`, {
        headers: JSON_HEADERS,
        redirect: 'follow',
        cache: 'no-store',
    });
    if (!response.ok) throw new Error(`Dailymotion metadata returned ${response.status}`);
    return response.json() as Promise<DailymotionMetadata>;
}

function masterHls(metadata: DailymotionMetadata): URL | null {
    for (const sources of Object.values(metadata.qualities || {})) {
        if (!Array.isArray(sources)) continue;
        const source = sources.find((item) =>
            typeof item?.url === 'string'
            && item.url.length > 0
            && (item.type?.toLowerCase().includes('mpegurl') || item.url.includes('.m3u8'))
        );
        if (source?.url) return safeTarget(source.url.split('#')[0]);
    }
    return null;
}

function relayUrl(request: NextRequest, id: string, absoluteTarget: string): string {
    const url = new URL('/api/dailymotion-hls', request.nextUrl.origin);
    url.searchParams.set('id', id);
    url.searchParams.set('target', absoluteTarget);
    return `${url.pathname}?${url.searchParams.toString()}`;
}

function rewriteUri(base: URL, raw: string, request: NextRequest, id: string): string {
    try {
        const target = new URL(raw, base);
        if (!allowedHost(target.hostname) || target.protocol !== 'https:') return raw;
        return relayUrl(request, id, target.toString());
    } catch {
        return raw;
    }
}

function rewritePlaylist(text: string, base: URL, request: NextRequest, id: string): string {
    return text
        .split(/\r?\n/)
        .map((line) => {
            const trimmed = line.trim();
            if (!trimmed) return line;
            if (!trimmed.startsWith('#')) {
                return rewriteUri(base, trimmed, request, id);
            }
            return line.replace(/URI="([^"]+)"/g, (_match, uri: string) =>
                `URI="${rewriteUri(base, uri, request, id)}"`
            );
        })
        .join('\n');
}

function isPlaylist(target: URL, response: Response): boolean {
    const contentType = response.headers.get('content-type')?.toLowerCase() || '';
    return target.pathname.toLowerCase().endsWith('.m3u8')
        || contentType.includes('mpegurl')
        || contentType.includes('vnd.apple.mpegurl');
}

function copyHeader(from: Headers, to: Headers, name: string) {
    const value = from.get(name);
    if (value) to.set(name, value);
}

async function handle(request: NextRequest, headOnly: boolean) {
    const id = request.nextUrl.searchParams.get('id')?.trim() || '';
    if (!/^[a-zA-Z0-9]+$/.test(id)) return failure('Invalid Dailymotion id', 400);

    let target: URL | null = null;
    const requestedTarget = request.nextUrl.searchParams.get('target')?.trim();
    if (requestedTarget) {
        target = safeTarget(requestedTarget);
        if (!target) return failure('Dailymotion relay target is not allowed', 403);
    } else {
        try {
            target = masterHls(await metadataFor(id));
        } catch (error) {
            return failure(error instanceof Error ? error.message : 'Unable to resolve Dailymotion HLS');
        }
        if (!target) return failure('Dailymotion HLS stream not available');
    }

    const upstreamHeaders = new Headers({
        Accept: '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'User-Agent': USER_AGENT,
        Referer: `https://www.dailymotion.com/video/${id}`,
        Origin: 'https://www.dailymotion.com',
    });
    const range = request.headers.get('range');
    if (range) upstreamHeaders.set('Range', range);

    let upstream: Response;
    try {
        upstream = await fetch(target.toString(), {
            method: 'GET',
            headers: upstreamHeaders,
            redirect: 'follow',
            cache: 'no-store',
        });
    } catch {
        return failure('Unable to fetch Dailymotion HLS resource');
    }

    if (!upstream.ok || !upstream.body) {
        void upstream.body?.cancel();
        return failure(`Dailymotion HLS resource returned ${upstream.status}`);
    }

    const commonHeaders = new Headers();
    commonHeaders.set('Cache-Control', 'private, no-store');
    commonHeaders.set('Cross-Origin-Resource-Policy', 'same-origin');
    commonHeaders.set('X-Robots-Tag', 'noindex, nofollow, noarchive');

    if (isPlaylist(target, upstream)) {
        if (headOnly) {
            void upstream.body.cancel();
            commonHeaders.set('Content-Type', 'application/vnd.apple.mpegurl; charset=utf-8');
            return new NextResponse(null, { status: 200, headers: commonHeaders });
        }
        const text = await upstream.text();
        const rewritten = rewritePlaylist(text, target, request, id);
        commonHeaders.set('Content-Type', 'application/vnd.apple.mpegurl; charset=utf-8');
        commonHeaders.set('Content-Length', String(new TextEncoder().encode(rewritten).byteLength));
        return new NextResponse(rewritten, { status: 200, headers: commonHeaders });
    }

    for (const name of ['content-type', 'content-length', 'content-range', 'accept-ranges', 'etag', 'last-modified']) {
        copyHeader(upstream.headers, commonHeaders, name);
    }
    if (headOnly) {
        void upstream.body.cancel();
        return new NextResponse(null, { status: upstream.status, headers: commonHeaders });
    }
    return new NextResponse(upstream.body, { status: upstream.status, headers: commonHeaders });
}

export async function GET(request: NextRequest) {
    return handle(request, false);
}

export async function HEAD(request: NextRequest) {
    return handle(request, true);
}
