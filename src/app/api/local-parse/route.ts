import { NextRequest, NextResponse } from 'next/server';

import type { PodcastEpisodeInfo, UnifiedParseResult, VideoQualityOption } from '@/lib/types';

const USER_AGENT =
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36';

const JSON_HEADERS = {
    Accept: 'application/json,text/plain,*/*',
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
    };
    request?: {
        files?: {
            progressive?: VimeoProgressive[];
        };
    };
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

type AppleLookupItem = {
    wrapperType?: string;
    kind?: string;
    trackId?: number;
    collectionId?: number;
    trackName?: string;
    collectionName?: string;
    artistName?: string;
    episodeUrl?: string;
    trackTimeMillis?: number;
    releaseDate?: string;
    artworkUrl600?: string;
    artworkUrl100?: string;
    feedUrl?: string;
};

type AppleLookupPayload = {
    resultCount?: number;
    results?: AppleLookupItem[];
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
        error: 'First-party parser does not handle this platform',
        url: sourceUrl,
    }, 422);
}

function upstreamFailure(sourceUrl: string, platform: string, message: string) {
    return noStoreJson({
        success: false,
        code: 'UPSTREAM_ERROR',
        status: 502,
        error: message,
        details: { platform, parser: 'galaxy-local' },
        url: sourceUrl,
    }, 502);
}

function parseUrl(raw: string): URL | null {
    try {
        const url = new URL(raw);
        if (url.protocol !== 'https:' && url.protocol !== 'http:') return null;
        return url;
    } catch {
        return null;
    }
}

function highestPoster(posters?: Record<string, string>): string | null {
    if (!posters) return null;
    const entries = Object.entries(posters)
        .filter(([, value]) => typeof value === 'string' && value.length > 0)
        .sort(([a], [b]) => Number(b) - Number(a));
    return entries[0]?.[1] || null;
}

function localMediaUrl(params: Record<string, string | number | undefined>): string {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
        if (value !== undefined && String(value).length > 0) {
            query.set(key, String(value));
        }
    }
    return `/api/local-media?${query.toString()}`;
}

function extractVimeoId(url: URL): string | null {
    if (!/(^|\.)vimeo\.com$/i.test(url.hostname)) return null;
    const match = url.pathname.match(/(?:video\/)?(\d{5,})/);
    return match?.[1] || null;
}

function extractDailymotionId(url: URL): string | null {
    const host = url.hostname.toLowerCase();
    if (host === 'dai.ly') {
        return url.pathname.split('/').filter(Boolean)[0] || null;
    }
    if (!host.endsWith('dailymotion.com')) return null;
    const match = url.pathname.match(/(?:video|embed\/video)\/([a-zA-Z0-9]+)/);
    return match?.[1] || null;
}

function extractApplePodcastIds(url: URL): { showId: string; episodeId: string | null } | null {
    if (!/(^|\.)podcasts\.apple\.com$/i.test(url.hostname)) return null;
    const match = url.pathname.match(/id(\d{5,})/i);
    if (!match) return null;
    return {
        showId: match[1],
        episodeId: url.searchParams.get('i'),
    };
}

async function parseVimeo(sourceUrl: string, id: string): Promise<UnifiedParseResult> {
    const response = await fetch(`https://player.vimeo.com/video/${encodeURIComponent(id)}/config`, {
        headers: JSON_HEADERS,
        redirect: 'follow',
        cache: 'no-store',
    });
    if (!response.ok) {
        throw new Error(`Vimeo config returned ${response.status}`);
    }

    const config = await response.json() as VimeoConfig;
    const progressive = (config.request?.files?.progressive || [])
        .filter((item) => typeof item.url === 'string' && item.url.length > 0)
        .sort((a, b) => (b.height || 0) - (a.height || 0));

    if (!progressive.length) {
        throw new Error('Vimeo did not expose a progressive media stream');
    }

    const qualityOptions: VideoQualityOption[] = progressive.map((item, index) => {
        const height = item.height || Number.parseInt(item.quality || '', 10) || undefined;
        return {
            quality: height ? String(height) : item.quality || String(index),
            label: height ? `${height}p` : item.quality,
            width: item.width,
            height,
            fps: item.fps,
            ext: item.mime?.includes('mp4') ? 'mp4' : undefined,
            downloadUrl: localMediaUrl({
                platform: 'vimeo',
                id,
                quality: height ? String(height) : item.quality || 'best',
            }),
        };
    });

    const best = qualityOptions[0]?.downloadUrl || localMediaUrl({ platform: 'vimeo', id, quality: 'best' });
    return {
        success: true,
        data: {
            title: config.video?.title || `Vimeo ${id}`,
            cover: highestPoster(config.video?.thumbs) || config.video?.thumb || null,
            platform: 'vimeo',
            downloadAudioUrl: null,
            downloadVideoUrl: best,
            originDownloadAudioUrl: null,
            originDownloadVideoUrl: best,
            videoAudioMode: 'muxed',
            mediaActions: {
                video: 'direct-download',
                audio: 'extract-audio',
            },
            qualityOptions,
            url: sourceUrl,
            duration: config.video?.duration,
            kind: 'video',
        },
    };
}

function dailymotionMp4Qualities(metadata: DailymotionMetadata): Array<{ quality: string; source: DailymotionSource }> {
    const output: Array<{ quality: string; source: DailymotionSource }> = [];
    for (const [quality, sources] of Object.entries(metadata.qualities || {})) {
        if (!Array.isArray(sources)) continue;
        const source = sources.find((item) =>
            typeof item?.url === 'string'
            && item.url.length > 0
            && (item.type?.includes('mp4') || item.url.includes('.mp4'))
        );
        if (source) output.push({ quality, source });
    }
    return output.sort((a, b) => Number.parseInt(b.quality, 10) - Number.parseInt(a.quality, 10));
}

async function parseDailymotion(sourceUrl: string, id: string): Promise<UnifiedParseResult> {
    const response = await fetch(`https://www.dailymotion.com/player/metadata/video/${encodeURIComponent(id)}`, {
        headers: JSON_HEADERS,
        redirect: 'follow',
        cache: 'no-store',
    });
    if (!response.ok) {
        throw new Error(`Dailymotion metadata returned ${response.status}`);
    }

    const metadata = await response.json() as DailymotionMetadata;
    const formats = dailymotionMp4Qualities(metadata);
    if (!formats.length) {
        throw new Error('Dailymotion did not expose a progressive MP4 stream');
    }

    const qualityOptions: VideoQualityOption[] = formats.map(({ quality }) => {
        const height = Number.parseInt(quality, 10) || undefined;
        return {
            quality,
            label: height ? `${height}p` : quality,
            height,
            ext: 'mp4',
            downloadUrl: localMediaUrl({ platform: 'dailymotion', id, quality }),
        };
    });
    const best = qualityOptions[0]?.downloadUrl || localMediaUrl({ platform: 'dailymotion', id, quality: 'best' });

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
            mediaActions: {
                video: 'direct-download',
                audio: 'extract-audio',
            },
            qualityOptions,
            url: sourceUrl,
            duration: metadata.duration,
            kind: 'video',
        },
    };
}

function isPodcastEpisode(item: AppleLookupItem): boolean {
    return item.kind === 'podcast-episode'
        || item.wrapperType === 'podcastEpisode'
        || typeof item.episodeUrl === 'string';
}

function toPodcastEpisode(showId: string, item: AppleLookupItem): PodcastEpisodeInfo | null {
    if (!isPodcastEpisode(item) || !item.trackId || !item.episodeUrl) return null;
    return {
        id: String(item.trackId),
        title: item.trackName || `Episode ${item.trackId}`,
        cover: item.artworkUrl600 || item.artworkUrl100 || null,
        duration: item.trackTimeMillis ? Math.round(item.trackTimeMillis / 1000) : undefined,
        releaseDate: item.releaseDate,
        downloadAudioUrl: localMediaUrl({
            platform: 'apple_podcasts',
            showId,
            episodeId: item.trackId,
        }),
        originDownloadAudioUrl: localMediaUrl({
            platform: 'apple_podcasts',
            showId,
            episodeId: item.trackId,
        }),
    };
}

async function fetchAppleLookup(showId: string): Promise<AppleLookupPayload> {
    const lookup = new URL('https://itunes.apple.com/lookup');
    lookup.searchParams.set('id', showId);
    lookup.searchParams.set('entity', 'podcastEpisode');
    lookup.searchParams.set('limit', '200');
    const response = await fetch(lookup, {
        headers: JSON_HEADERS,
        redirect: 'follow',
        cache: 'no-store',
    });
    if (!response.ok) {
        throw new Error(`Apple lookup returned ${response.status}`);
    }
    return response.json() as Promise<AppleLookupPayload>;
}

async function parseApplePodcasts(
    sourceUrl: string,
    showId: string,
    requestedEpisodeId: string | null,
): Promise<UnifiedParseResult> {
    const lookup = await fetchAppleLookup(showId);
    const items = Array.isArray(lookup.results) ? lookup.results : [];
    const show = items.find((item) => !isPodcastEpisode(item));
    const episodes = items
        .map((item) => toPodcastEpisode(showId, item))
        .filter((item): item is PodcastEpisodeInfo => Boolean(item));

    if (!episodes.length) {
        throw new Error('Apple lookup returned no downloadable podcast episodes');
    }

    const requestedEpisode = requestedEpisodeId
        ? episodes.find((episode) => episode.id === requestedEpisodeId)
        : null;

    if (requestedEpisode) {
        return {
            success: true,
            data: {
                title: requestedEpisode.title,
                cover: requestedEpisode.cover || show?.artworkUrl600 || show?.artworkUrl100 || null,
                platform: 'apple_podcasts',
                downloadAudioUrl: requestedEpisode.downloadAudioUrl || null,
                downloadVideoUrl: null,
                originDownloadAudioUrl: requestedEpisode.originDownloadAudioUrl || null,
                originDownloadVideoUrl: null,
                videoAudioMode: 'pure_music',
                mediaActions: { video: 'hide', audio: 'direct-download' },
                url: sourceUrl,
                duration: requestedEpisode.duration,
                kind: 'audio',
                noteType: 'audio',
                currentEpisodeId: requestedEpisode.id,
            },
        };
    }

    return {
        success: true,
        data: {
            title: show?.collectionName || show?.trackName || episodes[0]?.title || `Apple Podcasts ${showId}`,
            desc: show?.artistName,
            cover: show?.artworkUrl600 || show?.artworkUrl100 || episodes[0]?.cover || null,
            platform: 'apple_podcasts',
            downloadAudioUrl: null,
            downloadVideoUrl: null,
            originDownloadAudioUrl: null,
            originDownloadVideoUrl: null,
            videoAudioMode: 'not_applicable',
            mediaActions: { video: 'hide', audio: 'hide' },
            url: sourceUrl,
            kind: 'picker',
            episodes,
        },
    };
}

export async function GET(request: NextRequest) {
    const sourceUrl = request.nextUrl.searchParams.get('url')?.trim() || '';
    if (!sourceUrl) {
        return noStoreJson({
            success: false,
            code: 'BAD_REQUEST',
            status: 400,
            error: 'Missing url parameter',
        }, 400);
    }

    const parsed = parseUrl(sourceUrl);
    if (!parsed) {
        return noStoreJson({
            success: false,
            code: 'BAD_REQUEST',
            status: 400,
            error: 'Invalid source URL',
            url: sourceUrl,
        }, 400);
    }

    const vimeoId = extractVimeoId(parsed);
    const dailymotionId = extractDailymotionId(parsed);
    const appleIds = extractApplePodcastIds(parsed);

    try {
        const result = vimeoId
            ? await parseVimeo(sourceUrl, vimeoId)
            : dailymotionId
                ? await parseDailymotion(sourceUrl, dailymotionId)
                : appleIds
                    ? await parseApplePodcasts(sourceUrl, appleIds.showId, appleIds.episodeId)
                    : null;

        if (!result) return unsupported(sourceUrl);
        return noStoreJson(result);
    } catch (error) {
        const platform = vimeoId
            ? 'vimeo'
            : dailymotionId
                ? 'dailymotion'
                : appleIds
                    ? 'apple_podcasts'
                    : 'unknown';
        console.warn('First-party parser failed', {
            platform,
            sourceUrl,
            error: error instanceof Error ? error.message : String(error),
        });
        return upstreamFailure(
            sourceUrl,
            platform,
            error instanceof Error ? error.message : 'First-party parser failed',
        );
    }
}
