import { NextRequest, NextResponse } from 'next/server';

import type { UnifiedParseResult, VideoQualityOption } from '@/lib/types';

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
    width?: number;
    height?: number;
    fps?: number;
    mime?: string;
};

type VimeoConfig = {
    video?: {
        title?: string;
        duration?: number;
        thumbs?: Record<string, string>;
        thumb?: string;
        files?: { progressive?: VimeoProgressive[] };
    };
    request?: {
        files?: { progressive?: VimeoProgressive[] };
    };
};

type VimeoOEmbed = {
    title?: string;
    thumbnail_url?: string;
    duration?: number;
    html?: string;
};

type DailymotionSource = {
    type?: string;
    url?: string;
};

type DailymotionMetadata = {
    title?: string;
    duration?: number;
    posters?: Record<string, string>;
    qualities?: Record<string, DailymotionSource[]>;
};

function noStoreJson(payload: UnifiedParseResult, status = 200) {
    const response = NextResponse.json(payload, { status });
    response.headers.set('Cache-Control', 'no-store');
    response.headers.set('X-Robots-Tag', 'noindex, nofollow, noarchive');
    return response;
}

function unsupported(sourceUrl: string) {
    return noStoreJson({
        success: false,
        code: 'UNSUPPORTED_PLATFORM',
        status: 422,
        error: 'Second-generation parser does not handle this platform',
        url: sourceUrl,
    }, 422);
}

function failure(sourceUrl: string, platform: string, error: unknown) {
    const message = error instanceof Error ? error.message : String(error);
    console.warn('Second-generation first-party parser failed', { platform, sourceUrl, error: message });
    return noStoreJson({
        success: false,
        code: 'UPSTREAM_ERROR',
        status: 502,
        error: message,
        details: { platform, parser: 'galaxy-local-v2' },
        url: sourceUrl,
    }, 502);
}

function safeUrl(raw: string): URL | null {
    try {
        const url = new URL(raw);
        return url.protocol === 'https:' || url.protocol === 'http:' ? url : null;
    } catch {
        return null;
    }
}

function extractVimeoId(url: URL): string | null {
    if (!/(^|\.)vimeo\.com$/i.test(url.hostname)) return null;
    return url.pathname.match(/(?:video\/)?(\d{5,})/)?.[1] || null;
}

function extractDailymotionId(url: URL): string | null {
    const hostname = url.hostname.toLowerCase();
    if (hostname === 'dai.ly') return url.pathname.split('/').filter(Boolean)[0] || null;
    if (!hostname.endsWith('dailymotion.com')) return null;
    return url.pathname.match(/(?:video|embed\/video)\/([a-zA-Z0-9]+)/)?.[1] || null;
}

function decodeHtml(value: string): string {
    return value
        .replace(/&amp;/g, '&')
        .replace(/&quot;/g, '"')
        .replace(/&#39;/g, "'")
        .replace(/\\u0026/gi, '&')
        .replace(/\\\//g, '/');
}

function highestPoster(posters?: Record<string, string>): string | null {
    if (!posters) return null;
    return Object.entries(posters)
        .filter(([, value]) => typeof value === 'string' && value.length > 0)
        .sort(([a], [b]) => Number(b) - Number(a))[0]?.[1] || null;
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

function iframeSrc(html: string | undefined): string | null {
    if (!html) return null;
    const value = html.match(/<iframe[^>]+src=["']([^"']+)["']/i)?.[1];
    return value ? decodeHtml(value) : null;
}

async function getVimeoEmbedUrl(id: string): Promise<{ url: string; oembed: VimeoOEmbed }> {
    const oembedUrl = new URL('https://vimeo.com/api/oembed.json');
    oembedUrl.searchParams.set('url', `https://vimeo.com/${id}`);
    const oembed = await fetchJson<VimeoOEmbed>(oembedUrl.toString(), {
        ...JSON_HEADERS,
        Referer: 'https://vimeo.com/',
    });
    const src = iframeSrc(oembed.html);
    if (!src) throw new Error('Vimeo oEmbed did not return an iframe URL');
    const embed = safeUrl(src);
    if (!embed || embed.hostname !== 'player.vimeo.com' || !embed.pathname.startsWith(`/video/${id}`)) {
        throw new Error('Vimeo oEmbed returned an unexpected iframe URL');
    }
    return { url: embed.toString(), oembed };
}

async function fetchVimeoConfig(id: string): Promise<{ config: VimeoConfig; embedUrl: string; oembed: VimeoOEmbed }> {
    const { url: embedUrl, oembed } = await getVimeoEmbedUrl(id);
    const page = await fetch(embedUrl, {
        headers: { ...HTML_HEADERS, Referer: `https://vimeo.com/${id}` },
        redirect: 'follow',
        cache: 'no-store',
    });

    if (page.ok) {
        const html = await page.text();
        for (const marker of [/\bplayerConfig\s*=\s*/i, /\bvimeo\.config\s*=\s*/i, /\bconfig\s*=\s*/i]) {
            const embedded = extractBalancedJson(html, marker);
            if (embedded && typeof embedded === 'object') {
                return { config: embedded as VimeoConfig, embedUrl, oembed };
            }
        }
        const configValue = html.match(/\bdata-config-url=["']([^"']+)["']/i)?.[1]
            || html.match(/["']config_url["']\s*:\s*["']([^"']+)["']/i)?.[1];
        if (configValue) {
            const configUrl = decodeHtml(configValue);
            const config = await fetchJson<VimeoConfig>(configUrl, {
                ...JSON_HEADERS,
                Referer: embedUrl,
                Origin: 'https://player.vimeo.com',
            });
            return { config, embedUrl, oembed };
        }
    }

    const configUrl = new URL(embedUrl);
    configUrl.pathname = `${configUrl.pathname.replace(/\/$/, '')}/config`;
    const config = await fetchJson<VimeoConfig>(configUrl.toString(), {
        ...JSON_HEADERS,
        Referer: embedUrl,
        Origin: 'https://player.vimeo.com',
    });
    return { config, embedUrl, oembed };
}

function progressiveFormats(config: VimeoConfig): VimeoProgressive[] {
    return (config.video?.files?.progressive || config.request?.files?.progressive || [])
        .filter((item) => typeof item.url === 'string' && item.url.length > 0)
        .sort((a, b) => (b.height || 0) - (a.height || 0));
}

async function parseVimeo(sourceUrl: string, id: string): Promise<UnifiedParseResult> {
    const { config, oembed } = await fetchVimeoConfig(id);
    const progressive = progressiveFormats(config);
    if (!progressive.length) throw new Error('Vimeo did not expose a progressive media stream');

    const qualityOptions: VideoQualityOption[] = progressive.map((format, index) => {
        const height = format.height || Number.parseInt(format.quality || '', 10) || undefined;
        const params = new URLSearchParams({ platform: 'vimeo', id, quality: height ? String(height) : format.quality || String(index) });
        return {
            quality: height ? String(height) : format.quality || String(index),
            label: height ? `${height}p` : format.quality,
            width: format.width,
            height,
            fps: format.fps,
            ext: format.mime?.includes('mp4') ? 'mp4' : undefined,
            downloadUrl: `/api/vimeo-media?${params.toString()}`,
        };
    });
    const best = qualityOptions[0]?.downloadUrl || `/api/vimeo-media?platform=vimeo&id=${encodeURIComponent(id)}&quality=best`;

    return {
        success: true,
        data: {
            title: config.video?.title || oembed.title || `Vimeo ${id}`,
            cover: highestPoster(config.video?.thumbs) || config.video?.thumb || oembed.thumbnail_url || null,
            platform: 'vimeo',
            downloadAudioUrl: null,
            downloadVideoUrl: best,
            originDownloadAudioUrl: null,
            originDownloadVideoUrl: best,
            videoAudioMode: 'muxed',
            mediaActions: { video: 'direct-download', audio: 'extract-audio' },
            qualityOptions,
            url: sourceUrl,
            duration: config.video?.duration || oembed.duration,
            kind: 'video',
        },
    };
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

function hasDailymotionHls(metadata: DailymotionMetadata): boolean {
    return Object.values(metadata.qualities || {}).some((sources) =>
        Array.isArray(sources) && sources.some((item) =>
            typeof item?.url === 'string'
            && item.url.length > 0
            && (item.type?.toLowerCase().includes('mpegurl') || item.url.includes('.m3u8'))
        )
    );
}

async function parseDailymotion(sourceUrl: string, id: string): Promise<UnifiedParseResult> {
    const metadata = await fetchJson<DailymotionMetadata>(
        `https://www.dailymotion.com/player/metadata/video/${encodeURIComponent(id)}`,
    );
    const formats = dailymotionMp4Formats(metadata);
    if (formats.length) {
        const qualityOptions: VideoQualityOption[] = formats.map(({ quality }) => {
            const height = Number.parseInt(quality, 10) || undefined;
            const params = new URLSearchParams({ platform: 'dailymotion', id, quality });
            return {
                quality,
                label: height ? `${height}p` : quality,
                height,
                ext: 'mp4',
                downloadUrl: `/api/local-media?${params.toString()}`,
            };
        });
        const best = qualityOptions[0]?.downloadUrl || `/api/local-media?platform=dailymotion&id=${encodeURIComponent(id)}&quality=best`;
        return {
            success: true,
            data: {
                title: metadata.title || `Dailymotion ${id}`,
                cover: highestPoster(metadata.posters),
                platform: 'dailymotion',
                downloadAudioUrl: null,
                downloadVideoUrl: best,
                originDownloadAudioUrl: null,
                originDownloadVideoUrl: best,
                videoAudioMode: 'muxed',
                mediaActions: { video: 'direct-download', audio: 'extract-audio' },
                qualityOptions,
                url: sourceUrl,
                duration: metadata.duration,
                kind: 'video',
            },
        };
    }

    if (!hasDailymotionHls(metadata)) throw new Error('Dailymotion did not expose a downloadable stream');
    const relay = `/api/dailymotion-hls?id=${encodeURIComponent(id)}`;
    return {
        success: true,
        data: {
            title: metadata.title || `Dailymotion ${id}`,
            cover: highestPoster(metadata.posters),
            platform: 'dailymotion',
            downloadAudioUrl: null,
            downloadVideoUrl: relay,
            originDownloadAudioUrl: null,
            originDownloadVideoUrl: relay,
            videoAudioMode: 'muxed',
            mediaActions: { video: 'browser-hls-download', audio: 'extract-audio' },
            url: sourceUrl,
            duration: metadata.duration,
            kind: 'video',
        },
    };
}

export async function GET(request: NextRequest) {
    const sourceUrl = request.nextUrl.searchParams.get('url')?.trim() || '';
    if (!sourceUrl) return noStoreJson({ success: false, code: 'BAD_REQUEST', status: 400, error: 'Missing url parameter' }, 400);
    const parsed = safeUrl(sourceUrl);
    if (!parsed) return noStoreJson({ success: false, code: 'BAD_REQUEST', status: 400, error: 'Invalid source URL', url: sourceUrl }, 400);

    const vimeoId = extractVimeoId(parsed);
    const dailymotionId = extractDailymotionId(parsed);
    try {
        if (vimeoId) return noStoreJson(await parseVimeo(sourceUrl, vimeoId));
        if (dailymotionId) return noStoreJson(await parseDailymotion(sourceUrl, dailymotionId));
        return unsupported(sourceUrl);
    } catch (error) {
        return failure(sourceUrl, vimeoId ? 'vimeo' : 'dailymotion', error);
    }
}
