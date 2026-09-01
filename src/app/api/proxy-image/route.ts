'use server';

import { NextRequest, NextResponse } from 'next/server';

import { isSafePublicHttpUrl } from '@/lib/public-url';
import { setXRobotsTag } from '@/lib/seo';

const ALLOWED_IMAGE_HOSTS = [
    '*',
];

const DEFAULT_ACCEPT =
    'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8';
const MAX_REDIRECTS = 5;

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
    // Keep the legacy literal guard as defense in depth while the shared policy
    // also covers credentials, reserved ranges, mapped IPv6 and local names.
    return !isPrivateIpv4(host);
}

function isAllowedImageHost(hostname: string): boolean {
    const normalized = hostname.toLowerCase();
    if (ALLOWED_IMAGE_HOSTS.includes('*')) {
        return true;
    }
    return ALLOWED_IMAGE_HOSTS.some(
        (host) => normalized === host || normalized.endsWith(`.${host}`)
    );
}

function getReferer(hostname: string): string | undefined {
    const normalized = hostname.toLowerCase();
    if (normalized.endsWith('douyinpic.com')) {
        return 'https://www.douyin.com/';
    }
    if (normalized.endsWith('xhscdn.com') || normalized.endsWith('xiaohongshu.com')) {
        return 'https://www.xiaohongshu.com/';
    }
    if (
        normalized.endsWith('tiktokcdn.com') ||
        normalized.endsWith('tiktokcdn-us.com') ||
        normalized.endsWith('tiktok.com')
    ) {
        return 'https://www.tiktok.com/';
    }
    if (
        normalized.endsWith('instagram.com') ||
        normalized.endsWith('cdninstagram.com') ||
        normalized.endsWith('fbcdn.net')
    ) {
        return 'https://www.instagram.com/';
    }
    if (normalized.endsWith('nimg.jp')) {
        return 'https://www.nicovideo.jp/';
    }
    if (normalized.endsWith('mmbiz.qpic.cn')) {
        return 'https://mp.weixin.qq.com/';
    }
    if (
        normalized.endsWith('twimg.com') ||
        normalized.endsWith('x.com') ||
        normalized.endsWith('twitter.com')
    ) {
        return 'https://x.com/';
    }
    return undefined;
}

function isHttpProtocol(protocol: string): boolean {
    return protocol === 'http:' || protocol === 'https:';
}

// 有些 CDN 会把图片当二进制发（Bluesky 的 video.bsky.app 缩略图就是
// application/octet-stream），只看 Content-Type 会把好图判成非图片。
const GENERIC_BINARY_CONTENT_TYPES = new Set([
    '',
    'application/octet-stream',
    'binary/octet-stream',
    'application/binary',
]);

function startsWithBytes(bytes: Uint8Array, signature: number[], offset = 0): boolean {
    if (bytes.length < offset + signature.length) {
        return false;
    }
    return signature.every((byte, index) => bytes[offset + index] === byte);
}

/**
 * 按 magic number 认图片类型。Content-Type 不可信时才用。
 */
function sniffImageContentType(bytes: Uint8Array): string | undefined {
    if (startsWithBytes(bytes, [0xff, 0xd8, 0xff])) {
        return 'image/jpeg';
    }
    if (startsWithBytes(bytes, [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])) {
        return 'image/png';
    }
    if (startsWithBytes(bytes, [0x47, 0x49, 0x46, 0x38])) {
        return 'image/gif';
    }
    if (startsWithBytes(bytes, [0x42, 0x4d])) {
        return 'image/bmp';
    }
    // RIFF....WEBP
    if (startsWithBytes(bytes, [0x52, 0x49, 0x46, 0x46]) && startsWithBytes(bytes, [0x57, 0x45, 0x42, 0x50], 8)) {
        return 'image/webp';
    }
    // ....ftypavif / ftypavis
    if (startsWithBytes(bytes, [0x66, 0x74, 0x79, 0x70], 4)) {
        const brand = String.fromCharCode(...bytes.slice(8, 12));
        if (brand === 'avif' || brand === 'avis') {
            return 'image/avif';
        }
    }
    return undefined;
}

function normalizeUpstreamUrl(url: URL): URL {
    const normalizedUrl = new URL(url.toString());
    if (normalizedUrl.protocol === 'http:') {
        normalizedUrl.protocol = 'https:';
    }
    return normalizedUrl;
}

async function fetchUpstreamImage(initialUrl: URL, upstreamHeaders: Headers): Promise<Response> {
    let current = normalizeUpstreamUrl(initialUrl);
    for (let redirectCount = 0; redirectCount <= MAX_REDIRECTS; redirectCount += 1) {
        if (!isSafePublicImageUrl(current)) {
            throw new Error('Image redirect target is not allowed');
        }
        const response = await fetch(current.toString(), {
            method: 'GET',
            headers: upstreamHeaders,
            redirect: 'manual',
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

function tryDecodeURIComponent(value: string): string {
    try {
        return decodeURIComponent(value);
    } catch {
        return value;
    }
}

function unwrapNestedImageProxyUrl(targetUrl: URL): URL {
    const host = targetUrl.hostname.toLowerCase();
    const isKnownNestedProxyHost = NESTED_IMAGE_PROXY_HOSTS.has(host);
    const isImageProxyPath = targetUrl.pathname === '/api/image-proxy';
    if (!isKnownNestedProxyHost || !isImageProxyPath) {
        return targetUrl;
    }

    const nestedUrlParam = targetUrl.searchParams.get('url');
    if (!nestedUrlParam) {
        return targetUrl;
    }

    // Some upstream responses double-encode the nested url query parameter.
    let decoded = nestedUrlParam;
    for (let i = 0; i < 2; i += 1) {
        const nextDecoded = tryDecodeURIComponent(decoded);
        if (nextDecoded === decoded) {
            break;
        }
        decoded = nextDecoded;
    }

    try {
        const nestedUrl = new URL(decoded);
        if (!isSafePublicImageUrl(nestedUrl)) {
            return targetUrl;
        }
        return nestedUrl;
    } catch {
        return targetUrl;
    }
}

export async function GET(request: NextRequest) {
    const rawUrl = request.nextUrl.searchParams.get('url');
    if (!rawUrl) {
        const response = NextResponse.json({ error: 'Missing "url" query parameter' }, { status: 400 });
        setXRobotsTag(response.headers, ['noindex', 'nofollow', 'noarchive', 'noimageindex']);
        return response;
    }

    let targetUrl: URL;
    try {
        targetUrl = new URL(rawUrl);
    } catch {
        const response = NextResponse.json({ error: 'Invalid image url' }, { status: 400 });
        setXRobotsTag(response.headers, ['noindex', 'nofollow', 'noarchive', 'noimageindex']);
        return response;
    }

    targetUrl = unwrapNestedImageProxyUrl(targetUrl);

    if (!isSafePublicImageUrl(targetUrl)) {
        const response = NextResponse.json({ error: 'Only public http(s) image URLs are allowed' }, { status: 400 });
        setXRobotsTag(response.headers, ['noindex', 'nofollow', 'noarchive', 'noimageindex']);
        return response;
    }

    if (!isAllowedImageHost(targetUrl.hostname)) {
        const response = NextResponse.json({ error: 'Host is not allowed' }, { status: 403 });
        setXRobotsTag(response.headers, ['noindex', 'nofollow', 'noarchive', 'noimageindex']);
        return response;
    }

    const upstreamUrl = normalizeUpstreamUrl(targetUrl);

    const upstreamHeaders = new Headers();
    upstreamHeaders.set('Accept', DEFAULT_ACCEPT);
    upstreamHeaders.set(
        'User-Agent',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'
    );

    const referer = getReferer(targetUrl.hostname);
    if (referer) {
        upstreamHeaders.set('Referer', referer);
    }

    let upstreamResponse: Response;
    try {
        upstreamResponse = await fetchUpstreamImage(upstreamUrl, upstreamHeaders);
    } catch (error) {
        console.error('Failed to fetch upstream image', {
            url: upstreamUrl.toString(),
            error: error instanceof Error ? error.message : String(error),
        });
        const response = NextResponse.json({ error: 'Failed to fetch image from upstream' }, { status: 502 });
        setXRobotsTag(response.headers, ['noindex', 'nofollow', 'noarchive', 'noimageindex']);
        return response;
    }

    if (!upstreamResponse.ok || !upstreamResponse.body) {
        const response = NextResponse.json(
            { error: `Upstream image request failed with status ${upstreamResponse.status}` },
            { status: 502 }
        );
        setXRobotsTag(response.headers, ['noindex', 'nofollow', 'noarchive', 'noimageindex']);
        return response;
    }

    const upstreamContentType = (upstreamResponse.headers.get('content-type') || '')
        .split(';')[0]
        .trim()
        .toLowerCase();

    // Content-Type 已经说是图片就直接透传，省掉把整张图读进内存
    if (upstreamContentType.startsWith('image/')) {
        const headers = new Headers();
        headers.set('Content-Type', upstreamContentType);
        headers.set('Cache-Control', 'public, max-age=3600, s-maxage=86400, stale-while-revalidate=86400');
        headers.set('Cross-Origin-Resource-Policy', 'same-origin');
        setXRobotsTag(headers, ['noindex', 'nofollow', 'noarchive', 'noimageindex']);

        const contentLength = upstreamResponse.headers.get('content-length');
        if (contentLength) {
            headers.set('Content-Length', contentLength);
        }

        return new NextResponse(upstreamResponse.body, { status: 200, headers });
    }

    // 只有笼统的二进制类型才值得再嗅一次；text/html、application/json 这类
    // 明确不是图片的直接拒掉，不用把响应体读进来。
    if (!GENERIC_BINARY_CONTENT_TYPES.has(upstreamContentType)) {
        const response = NextResponse.json({ error: 'Upstream response is not an image' }, { status: 415 });
        setXRobotsTag(response.headers, ['noindex', 'nofollow', 'noarchive', 'noimageindex']);
        return response;
    }

    const buffer = new Uint8Array(await upstreamResponse.arrayBuffer());
    const sniffedContentType = sniffImageContentType(buffer);
    if (!sniffedContentType) {
        const response = NextResponse.json({ error: 'Upstream response is not an image' }, { status: 415 });
        setXRobotsTag(response.headers, ['noindex', 'nofollow', 'noarchive', 'noimageindex']);
        return response;
    }

    const headers = new Headers();
    headers.set('Content-Type', sniffedContentType);
    headers.set('Content-Length', String(buffer.byteLength));
    headers.set('Cache-Control', 'public, max-age=3600, s-maxage=86400, stale-while-revalidate=86400');
    headers.set('Cross-Origin-Resource-Policy', 'same-origin');
    setXRobotsTag(headers, ['noindex', 'nofollow', 'noarchive', 'noimageindex']);

    return new NextResponse(buffer, { status: 200, headers });
}
