import { NextRequest, NextResponse } from 'next/server';

const USER_AGENT =
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36';

const JSON_HEADERS = {
    Accept: 'application/json,text/plain,*/*',
    'User-Agent': USER_AGENT,
};

type VimeoProgressive = {
    url?: string;
    quality?: string;
    height?: number;
};

type VimeoConfig = {
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
    filename: string;
};

function failure(message: string, status: number) {
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

async function fetchJson<T>(url: string): Promise<T> {
    const response = await fetch(url, {
        headers: JSON_HEADERS,
        redirect: 'follow',
        cache: 'no-store',
    });
    if (!response.ok) {
        throw new Error(`Metadata request failed (${response.status})`);
    }
    return response.json() as Promise<T>;
}

function requestedQuality(request: NextRequest): string {
    return request.nextUrl.searchParams.get('quality')?.trim() || 'best';
}

function pickVimeoProgressive(config: VimeoConfig, quality: string): VimeoProgressive | null {
    const progressive = (config.request?.files?.progressive || [])
        .filter((item) => typeof item.url === 'string' && item.url.length > 0)
        .sort((a, b) => (b.height || 0) - (a.height || 0));
    if (!progressive.length) return null;
    if (quality === 'best') return progressive[0];

    const targetHeight = Number.parseInt(quality, 10);
    if (Number.isFinite(targetHeight)) {
        return progressive.find((item) => item.height === targetHeight)
            || progressive.find((item) => (item.height || 0) <= targetHeight)
            || progressive[progressive.length - 1];
    }

    return progressive.find((item) => item.quality === quality) || progressive[0];
}

async function resolveVimeo(request: NextRequest): Promise<ResolvedMedia> {
    const id = request.nextUrl.searchParams.get('id')?.trim();
    if (!id || !/^\d{5,}$/.test(id)) throw new Error('Invalid Vimeo id');
    const config = await fetchJson<VimeoConfig>(
        `https://player.vimeo.com/video/${encodeURIComponent(id)}/config`,
    );
    const selected = pickVimeoProgressive(config, requestedQuality(request));
    if (!selected?.url) throw new Error('Vimeo progressive stream not available');
    return {
        url: selected.url,
        referer: `https://player.vimeo.com/video/${id}`,
        filename: `vimeo-${id}.mp4`,
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

async function resolveDailymotion(request: NextRequest): Promise<ResolvedMedia> {
    const id = request.nextUrl.searchParams.get('id')?.trim();
    if (!id || !/^[a-zA-Z0-9]+$/.test(id)) throw new Error('Invalid Dailymotion id');
    const metadata = await fetchJson<DailymotionMetadata>(
        `https://www.dailymotion.com/player/metadata/video/${encodeURIComponent(id)}`,
    );
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

function isAppleEpisode(item: AppleLookupItem): boolean {
    return item.kind === 'podcast-episode'
        || item.wrapperType === 'podcastEpisode'
        || typeof item.episodeUrl === 'string';
}

async function resolveApplePodcast(request: NextRequest): Promise<ResolvedMedia> {
    const showId = request.nextUrl.searchParams.get('showId')?.trim();
    const episodeId = request.nextUrl.searchParams.get('episodeId')?.trim();
    if (!showId || !/^\d+$/.test(showId) || !episodeId || !/^\d+$/.test(episodeId)) {
        throw new Error('Invalid Apple Podcasts identifiers');
    }

    const lookup = new URL('https://itunes.apple.com/lookup');
    lookup.searchParams.set('id', showId);
    lookup.searchParams.set('entity', 'podcastEpisode');
    lookup.searchParams.set('limit', '200');
    const payload = await fetchJson<AppleLookupPayload>(lookup.toString());
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

function copyHeader(from: Headers, to: Headers, name: string) {
    const value = from.get(name);
    if (value) to.set(name, value);
}

async function handle(request: NextRequest, headOnly: boolean) {
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
        return new NextResponse(null, {
            status: upstream.status,
            headers: responseHeaders,
        });
    }

    return new NextResponse(upstream.body, {
        status: upstream.status,
        headers: responseHeaders,
    });
}

export async function GET(request: NextRequest) {
    return handle(request, false);
}

export async function HEAD(request: NextRequest) {
    return handle(request, true);
}
