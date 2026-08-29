import { API_ENDPOINT_CANDIDATES } from '@/lib/config';
import type { SubtitleTrack, VideoQualityOption } from '@/lib/types';

export type MediaDownloadType = 'video' | 'audio';

export interface QualityChoice extends VideoQualityOption {
    source: 'parser' | 'preset';
}

export const VIDEO_QUALITY_PRESETS: readonly QualityChoice[] = [
    { quality: 'best', label: 'Best available', source: 'preset' },
    { quality: '4320', label: '8K · 4320p', height: 4320, source: 'preset' },
    { quality: '2160', label: '4K · 2160p', height: 2160, source: 'preset' },
    { quality: '1440', label: '2K · 1440p', height: 1440, source: 'preset' },
    { quality: '1080', label: 'Full HD · 1080p', height: 1080, source: 'preset' },
    { quality: '720', label: 'HD · 720p', height: 720, source: 'preset' },
    { quality: '480', label: 'SD · 480p', height: 480, source: 'preset' },
    { quality: '360', label: '360p', height: 360, source: 'preset' },
    { quality: '240', label: '240p', height: 240, source: 'preset' },
    { quality: '144', label: '144p', height: 144, source: 'preset' },
] as const;

export const AUDIO_QUALITY_PRESETS = [
    { quality: 'best', label: 'Best available' },
    { quality: '320', label: '320 kbps' },
    { quality: '256', label: '256 kbps' },
    { quality: '192', label: '192 kbps' },
    { quality: '128', label: '128 kbps' },
    { quality: '64', label: '64 kbps' },
] as const;

function parseHeight(option: VideoQualityOption): number {
    if (typeof option.height === 'number' && Number.isFinite(option.height)) {
        return option.height;
    }

    const text = `${option.label || ''} ${option.quality || ''}`;
    const match = text.match(/(\d{3,4})\s*p?/i);
    return match ? Number(match[1]) : 0;
}

function buildQualityLabel(option: VideoQualityOption): string {
    if (option.label?.trim()) {
        return option.label.trim();
    }

    const height = parseHeight(option);
    const details = [
        height > 0 ? `${height}p` : option.quality,
        option.fps && option.fps > 30 ? `${Math.round(option.fps)}fps` : null,
        option.ext?.toUpperCase() || null,
        option.vcodec && option.vcodec !== 'none' ? option.vcodec.toUpperCase() : null,
    ].filter(Boolean);

    return details.join(' · ') || option.quality;
}

export function normalizeQualityOptions(options?: VideoQualityOption[] | null): QualityChoice[] {
    if (!options?.length) {
        return [...VIDEO_QUALITY_PRESETS];
    }

    const seen = new Set<string>();
    const normalized = options
        .filter((option) => typeof option?.quality === 'string' && option.quality.trim().length > 0)
        .map((option) => ({
            ...option,
            quality: option.quality.trim(),
            label: buildQualityLabel(option),
            source: 'parser' as const,
        }))
        .sort((a, b) => {
            const heightDiff = parseHeight(b) - parseHeight(a);
            if (heightDiff !== 0) return heightDiff;
            return (b.fps || 0) - (a.fps || 0);
        })
        .filter((option) => {
            const key = option.quality.toLowerCase();
            if (seen.has(key)) return false;
            seen.add(key);
            return true;
        });

    const hasBest = normalized.some((option) => option.quality.toLowerCase() === 'best');
    if (!hasBest) {
        normalized.unshift({
            quality: 'best',
            label: 'Best available',
            source: 'preset',
        });
    }

    return normalized;
}

type BuildSourceMediaDownloadInput = {
    sourceUrl: string;
    type: MediaDownloadType;
    quality?: string | null;
    formatId?: number | null;
};

function buildSourceMediaDownloadUrlForEndpoint(endpoint: string, {
    sourceUrl,
    type,
    quality,
    formatId,
}: BuildSourceMediaDownloadInput): string {
    const params = new URLSearchParams({
        url: sourceUrl.trim(),
        type,
    });

    if (quality?.trim()) {
        params.set('quality', quality.trim());
    }

    if (typeof formatId === 'number' && Number.isFinite(formatId)) {
        params.set('formatId', String(formatId));
    }

    const separator = endpoint.includes('?') ? '&' : '?';
    return `${endpoint}${separator}${params.toString()}`;
}

export function buildSourceMediaDownloadUrls(input: BuildSourceMediaDownloadInput): string[] {
    return API_ENDPOINT_CANDIDATES.unified.download.map((endpoint) =>
        buildSourceMediaDownloadUrlForEndpoint(endpoint, input)
    );
}

export function buildSourceMediaDownloadUrl(input: BuildSourceMediaDownloadInput): string {
    return buildSourceMediaDownloadUrls(input)[0];
}

type DownloadResolutionPayload = {
    success?: boolean;
    ready?: unknown;
    url?: unknown;
    downloadUrl?: unknown;
    data?: unknown;
    error?: unknown;
    message?: unknown;
};

function extractResolvedDownloadUrl(payload: DownloadResolutionPayload): string | null {
    const topLevel = typeof payload.url === 'string'
        ? payload.url
        : typeof payload.downloadUrl === 'string'
            ? payload.downloadUrl
            : null;
    if (topLevel?.trim()) return topLevel.trim();

    if (typeof payload.data === 'string' && payload.data.trim()) {
        return payload.data.trim();
    }

    if (payload.data && typeof payload.data === 'object') {
        const data = payload.data as Record<string, unknown>;
        const nested = typeof data.url === 'string'
            ? data.url
            : typeof data.downloadUrl === 'string'
                ? data.downloadUrl
                : typeof data.download_url === 'string'
                    ? data.download_url
                    : null;
        if (nested?.trim()) return nested.trim();
    }

    return null;
}

function responseLooksJson(response: Response): boolean {
    const contentType = response.headers.get('content-type')?.toLowerCase() || '';
    return contentType.includes('application/json') || contentType.includes('+json');
}

async function readResolutionPayload(response: Response): Promise<DownloadResolutionPayload> {
    try {
        return await response.json() as DownloadResolutionPayload;
    } catch {
        throw new Error('Download resolver returned invalid JSON');
    }
}

function resolutionError(response: Response, payload: DownloadResolutionPayload): Error {
    const message = typeof payload.error === 'string'
        ? payload.error
        : typeof payload.message === 'string'
            ? payload.message
            : `Download request failed (${response.status})`;
    return new Error(message);
}

function sourceAwareRequestCandidates(requestUrl: string): string[] {
    try {
        const parsed = new URL(requestUrl, 'http://localhost');
        if (parsed.pathname !== '/api/download') return [requestUrl];
        const query = parsed.search;
        const candidates = [requestUrl];
        for (const endpoint of API_ENDPOINT_CANDIDATES.unified.download) {
            const separator = endpoint.includes('?')
                ? (query ? '&' : '')
                : (query ? '?' : '');
            const queryWithoutPrefix = query.startsWith('?') ? query.slice(1) : query;
            candidates.push(`${endpoint}${separator}${queryWithoutPrefix}`);
        }
        return [...new Set(candidates)];
    } catch {
        return [requestUrl];
    }
}

async function resolveSingleSourceMediaDownloadUrl(requestUrl: string): Promise<string> {
    let headResponse: Response | null = null;
    try {
        headResponse = await fetch(requestUrl, {
            method: 'HEAD',
            cache: 'no-store',
        });
    } catch {
        // Legacy endpoints may not support HEAD. Fall through to GET.
    }

    if (headResponse?.ok) {
        if (!responseLooksJson(headResponse)) {
            void headResponse.body?.cancel();
            return requestUrl;
        }

        try {
            const payload = await readResolutionPayload(headResponse);
            if (payload.success !== false) {
                const resolvedUrl = extractResolvedDownloadUrl(payload);
                if (resolvedUrl) return resolvedUrl;
                if (payload.ready === true) return requestUrl;
            }
        } catch {
            // Empty JSON HEAD bodies are common on older resolver services.
        }
    } else {
        void headResponse?.body?.cancel();
    }

    const response = await fetch(requestUrl, {
        method: 'GET',
        cache: 'no-store',
    });

    if (responseLooksJson(response)) {
        const payload = await readResolutionPayload(response);
        if (!response.ok || payload.success === false) {
            throw resolutionError(response, payload);
        }

        const resolvedUrl = extractResolvedDownloadUrl(payload);
        if (!resolvedUrl) {
            if (payload.ready === true) return requestUrl;
            throw new Error('Download resolver did not return a media URL');
        }
        return resolvedUrl;
    }

    if (!response.ok) {
        void response.body?.cancel();
        throw new Error(`Download request failed (${response.status})`);
    }

    void response.body?.cancel();
    return requestUrl;
}

/**
 * Resolve a legacy JSON resolver or streaming endpoint. Source-aware download
 * requests automatically retry the optional first-party Container backend with
 * the exact same source/quality parameters when the primary endpoint fails.
 */
export async function resolveSourceMediaDownloadUrl(requestUrl: string): Promise<string> {
    let lastError: unknown = null;
    for (const candidate of sourceAwareRequestCandidates(requestUrl)) {
        try {
            return await resolveSingleSourceMediaDownloadUrl(candidate);
        } catch (error) {
            lastError = error;
        }
    }
    if (lastError instanceof Error) throw lastError;
    throw new Error('No media download endpoint is available');
}

export function resolveSubtitleUrl(track: SubtitleTrack): string | null {
    const value = track.downloadUrl || track.url;
    return typeof value === 'string' && value.trim() ? value.trim() : null;
}

export function getSubtitleDisplayName(track: SubtitleTrack): string {
    const base = track.label?.trim() || track.language?.trim() || 'Subtitle';
    return track.isAutoGenerated ? `${base} · auto` : base;
}

export function inferExtension(url: string | null | undefined, fallback: string): string {
    if (!url) return fallback;

    try {
        const pathname = new URL(url).pathname;
        const last = pathname.split('/').pop() || '';
        const match = last.match(/\.([a-z0-9]{2,6})$/i);
        if (match) return match[1].toLowerCase();
    } catch {
        // Ignore malformed URLs and use the fallback extension.
    }

    return fallback;
}

export function createMediaMetadata(result: {
    title: string;
    desc?: string;
    platform: string;
    url: string;
    duration?: number;
    cover?: string | null;
    qualityOptions?: VideoQualityOption[];
    subtitles?: SubtitleTrack[];
}) {
    return {
        title: result.title,
        description: result.desc || null,
        platform: result.platform,
        sourceUrl: result.url,
        durationSeconds: result.duration ?? null,
        cover: result.cover || null,
        qualityOptions: result.qualityOptions || [],
        subtitles: result.subtitles || [],
        exportedAt: new Date().toISOString(),
    };
}
