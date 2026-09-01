import { NextRequest, NextResponse } from 'next/server';

import { originalImageCandidates } from '@/lib/image-source';
import { isSafePublicHttpUrl } from '@/lib/public-url';
import { setXRobotsTag } from '@/lib/seo';
import {
    ByteLimitExceededError,
    declaredContentLength,
    limitReadableStream,
    sniffPrefixAndLimitStream,
} from '@/lib/stream-byte-limit';

const ALLOWED_IMAGE_HOSTS = [
    '*',
];

// Only request and serve inert raster formats. SVG is an active XML document
// format and must never be reflected through this same-origin proxy.
const PREVIEW_ACCEPT =
    'image/avif,image/webp,image/apng,image/png,image/jpeg,image/gif,image/bmp;q=0.9,application/octet-stream;q=0.2,*/*;q=0.1';
const DOWNLOAD_ACCEPT =
    'image/avif,image/webp,image/apng,image/png,image/jpeg,image/gif,image/bmp;q=0.9,application/octet-stream;q=0.2,*/*;q=0.1';
const MAX_REDIRECTS = 5;
const MAX_IMAGE_BYTES = 32 * 1024 * 1024;
const IMAGE_SNIFF_BYTES = 16;

const SAFE_RASTER_CONTENT_TYPES = new Set([
    'image/jpeg',
    'image/jpg',
    'image/png',
    'image/apng',
    'image/gif',
    'image/webp',
    'image/avif',
    'image/bmp',
]);

const NESTED_IMAGE_PROXY_HOSTS = new Set([
    'downloader-api.bhwa233.com',
]);

function isPrivateIpv4(hostname: string): boolean {
    const match = hostname.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
    if (!match) return false;
    const octets = match.slice(1).map(Number);
    if (octets.some((value) => value < 0 || value > 255)) return true;
    const [a, b] = octets;
    return a === 0
        || a === 10
        || a === 127
        || (a === 169 && b === 254)
        || (a === 172 && b >= 16 && b <= 31)
        || (a === 192 && b === 168)
        || (a === 100 && b >= 64 && b <= 127)
        || a >= 224;
}

function isSafePublicImageUrl(url: URL): boolean {
    if (!isHttpProtocol(url.protocol) || !isSafePublicHttpUrl(url)) return false;
    const host = url.hostname.toLowerCase().replace(/^\[|\]$/g, '');
    return !isPrivateIpv4(host);
}

function isAllowedImageHost(hostname: string): boolean {
    const normalized = hostname.toLowerCase();
    if (ALLOWED_IMAGE_HOSTS.includes('*')) return true;
    return ALLOWED_IMAGE_HOSTS.some(
        (host) => normalized === host || normalized.endsWith(`.${host}`)
    );
}

function getReferer(hostname: string): string | undefined {
    const normalized = hostname.toLowerCase();
    if (normalized.endsWith('douyinpic.com')) return 'https://www.douyin.com/';
    if (normalized.endsWith('xhscdn.com') || normalized.endsWith('xiaohongshu.com')) return 'https://www.xiaohongshu.com/';
    if (normalized.endsWith('tiktokcdn.com') || normalized.endsWith('tiktokcdn-us.com') || normalized.endsWith('tiktok.com')) return 'https://www.tiktok.com/';
    if (normalized.endsWith('instagram.com') || normalized.endsWith('cdninstagram.com') || normalized.endsWith('fbcdn.net')) return 'https://www.instagram.com/';
    if (normalized.endsWith('nimg.jp')) return 'https://www.nicovideo.jp/';
    if (normalized.endsWith('mmbiz.qpic.cn')) return 'https://mp.weixin.qq.com/';
    if (normalized.endsWith('twimg.com') || normalized.endsWith('x.com') || normalized.endsWith('twitter.com')) return 'https://x.com/';
    return undefined;
}

function sourceOriginReferer(value: string | null): string | undefined {
    if (!value) return undefined;
    try {
        const source = new URL(value);
        if (!isSafePublicHttpUrl(source)) return undefined;
        return `${source.origin}/`;
    } catch {
        return undefined;
    }
}

function isHttpProtocol(protocol: string): boolean {
    return protocol === 'http:' || protocol === 'https:';
}

const GENERIC_BINARY_CONTENT_TYPES = new Set([
    '',
    'application/octet-stream',
    'binary/octet-stream',
    'application/binary',
]);

function startsWithBytes(bytes: Uint8Array, signature: number[], offset = 0): boolean {
    if (bytes.length < offset + signature.length) return false;
    return signature.every((byte, index) => bytes[offset + index] === byte);
}

function sniffImageContentType(bytes: Uint8Array): string | undefined {
    if (startsWithBytes(bytes, [0xff, 0xd8, 0xff])) return 'image/jpeg';
    if (startsWithBytes(bytes, [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])) return 'image/png';
    if (startsWithBytes(bytes, [0x47, 0x49, 0x46, 0x38])) return 'image/gif';
    if (startsWithBytes(bytes, [0x42, 0x4d])) return 'image/bmp';
    if (startsWithBytes(bytes, [0x52, 0x49, 0x46, 0x46]) && startsWithBytes(bytes, [0x57, 0x45, 0x42, 0x50], 8)) return 'image/webp';
    if (startsWithBytes(bytes, [0x66, 0x74, 0x79, 0x70], 4)) {
        const brand = String.fromCharCode(...bytes.slice(8, 12));
        if (brand === 'avif' || brand === 'avis') return 'image/avif';
    }
    return undefined;
}

function normalizeUpstreamUrl(url: URL): URL {
    const normalizedUrl = new URL(url.toString());
    if (normalizedUrl.protocol === 'http:') normalizedUrl.protocol = 'https:';
    return normalizedUrl;
}

async function fetchUpstreamImage(initialUrl: URL, upstreamHeaders: Headers): Promise<Response> {
    let current = normalizeUpstreamUrl(initialUrl);
    for (let redirectCount = 0; redirectCount <= MAX_REDIRECTS; redirectCount += 1) {
        if (!isSafePublicImageUrl(current)) throw new Error('Image redirect target is not allowed');
        const response = await fetch(current.toString(), {
            method: 'GET',
            headers: upstreamHeaders,
            redirect: 'manual',
            cache: 'no-store',
        });
        if (response.status >= 300 && response.status < 400) {
            const location = response.headers.get('location');
            void response.body?.cancel();
            if (!location) throw new Error(`Image redirect ${response.status} has no Location`);
            current = normalizeUpstreamUrl(new URL(location, current));
            continue;
        }
        return response;
    }
    throw new Error('Image exceeded redirect limit');
}

async function fetchImageCandidates(rawUrls: string[], upstreamHeaders: Headers): Promise<Response> {
    let lastError: unknown = null;

    for (const rawUrl of rawUrls) {
        try {
            const candidate = new URL(rawUrl);
            if (!isSafePublicImageUrl(candidate)) {
                lastError = new Error('Image candidate is not allowed');
                continue;
            }
            const response = await fetchUpstreamImage(candidate, upstreamHeaders);
            const contentType = (response.headers.get('content-type') || '').split(';')[0]!.trim().toLowerCase();
            const imageLike = SAFE_RASTER_CONTENT_TYPES.has(contentType) || GENERIC_BINARY_CONTENT_TYPES.has(contentType);
            if (response.ok && response.body && imageLike) return response;
            void response.body?.cancel();
            lastError = new Error(`Image candidate failed (${response.status || 'invalid content'})`);
        } catch (error) {
            lastError = error;
        }
    }

    throw lastError ?? new Error('No image candidate could be fetched');
}

function tryDecodeURIComponent(value: string): string {
    try {
        return decodeURIComponent(value);
    } catch {
        return value;
    }
}

function unwrapNestedImageProxyUrl(targetUrl: URL): URL {
    const host = targetUrl.hostname.toLowerCase();
    if (!NESTED_IMAGE_PROXY_HOSTS.has(host) || targetUrl.pathname !== '/api/image-proxy') return targetUrl;
    const nestedUrlParam = targetUrl.searchParams.get('url');
    if (!nestedUrlParam) return targetUrl;

    let decoded = nestedUrlParam;
    for (let i = 0; i < 2; i += 1) {
        const nextDecoded = tryDecodeURIComponent(decoded);
        if (nextDecoded === decoded) break;
        decoded = nextDecoded;
    }

    try {
        const nestedUrl = new URL(decoded);
        return isSafePublicImageUrl(nestedUrl) ? nestedUrl : targetUrl;
    } catch {
        return targetUrl;
    }
}

function imageError(error: string, status: number): NextResponse {
    const response = NextResponse.json({ error }, { status });
    setXRobotsTag(response.headers, ['noindex', 'nofollow', 'noarchive', 'noimageindex']);
    return response;
}

function imageResponseHeaders(contentType: string, isDownload: boolean): Headers {
    const headers = new Headers();
    headers.set('Content-Type', contentType);
    headers.set('Cache-Control', isDownload
        ? 'private, no-store'
        : 'public, max-age=900, s-maxage=3600, stale-while-revalidate=3600');
    if (isDownload) headers.set('Content-Disposition', 'attachment; filename="image"');
    headers.set('Cross-Origin-Resource-Policy', 'same-origin');
    headers.set('X-Content-Type-Options', 'nosniff');
    headers.set('X-Galaxy-Max-Image-Bytes', String(MAX_IMAGE_BYTES));
    setXRobotsTag(headers, ['noindex', 'nofollow', 'noarchive', 'noimageindex']);
    return headers;
}

export async function GET(request: NextRequest) {
    const rawUrl = request.nextUrl.searchParams.get('url');
    if (!rawUrl) return imageError('Missing "url" query parameter', 400);

    let targetUrl: URL;
    try {
        targetUrl = new URL(rawUrl);
    } catch {
        return imageError('Invalid image url', 400);
    }

    targetUrl = unwrapNestedImageProxyUrl(targetUrl);
    if (!isSafePublicImageUrl(targetUrl)) return imageError('Only public http(s) image URLs are allowed', 400);
    if (!isAllowedImageHost(targetUrl.hostname)) return imageError('Host is not allowed', 403);

    const isDownload = request.nextUrl.searchParams.get('mode') === 'download';
    const upstreamHeaders = new Headers();
    upstreamHeaders.set('Accept', isDownload ? DOWNLOAD_ACCEPT : PREVIEW_ACCEPT);
    upstreamHeaders.set('Accept-Encoding', 'identity');
    upstreamHeaders.set(
        'User-Agent',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36'
    );

    const referer = sourceOriginReferer(request.nextUrl.searchParams.get('source')) || getReferer(targetUrl.hostname);
    if (referer) upstreamHeaders.set('Referer', referer);

    let upstreamResponse: Response;
    try {
        upstreamResponse = await fetchImageCandidates(originalImageCandidates(targetUrl.toString()), upstreamHeaders);
    } catch (error) {
        console.error('Failed to fetch upstream image', {
            url: targetUrl.toString(),
            error: error instanceof Error ? error.message : String(error),
        });
        return imageError('Failed to fetch image from upstream', 502);
    }

    const declaredLength = declaredContentLength(upstreamResponse.headers);
    if (declaredLength !== null && declaredLength > MAX_IMAGE_BYTES) {
        void upstreamResponse.body?.cancel();
        return imageError('Image exceeds 32 MiB proxy limit', 413);
    }

    const upstreamContentType = (upstreamResponse.headers.get('content-type') || '')
        .split(';')[0]
        .trim()
        .toLowerCase();

    if (SAFE_RASTER_CONTENT_TYPES.has(upstreamContentType)) {
        const normalizedContentType = upstreamContentType === 'image/jpg'
            ? 'image/jpeg'
            : upstreamContentType === 'image/apng'
                ? 'image/png'
                : upstreamContentType;
        const headers = imageResponseHeaders(normalizedContentType, isDownload);
        if (declaredLength !== null) headers.set('Content-Length', String(declaredLength));
        return new NextResponse(limitReadableStream(upstreamResponse.body!, MAX_IMAGE_BYTES), { status: 200, headers });
    }

    try {
        const { prefix, stream } = await sniffPrefixAndLimitStream(
            upstreamResponse.body!,
            MAX_IMAGE_BYTES,
            IMAGE_SNIFF_BYTES,
        );
        const sniffedContentType = sniffImageContentType(prefix);
        if (!sniffedContentType) {
            void stream.cancel();
            return imageError('Upstream response is not a supported raster image', 415);
        }

        const headers = imageResponseHeaders(sniffedContentType, isDownload);
        if (declaredLength !== null) headers.set('Content-Length', String(declaredLength));
        return new NextResponse(stream, { status: 200, headers });
    } catch (error) {
        if (error instanceof ByteLimitExceededError) {
            return imageError('Image exceeds 32 MiB proxy limit', 413);
        }
        throw error;
    }
}
