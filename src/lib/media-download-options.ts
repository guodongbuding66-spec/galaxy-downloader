import { API_ENDPOINTS } from '@/lib/config';
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

/**
 * Prefer parser-provided formats because their `quality` values are the exact
 * values understood by the backend. Fall back to common presets only when a
 * parser does not expose a format list.
 */
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
            // Radix Select values must be unique. If a parser exposes multiple
            // codecs for the same quality, retain the highest-ranked entry.
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

/**
 * Build a source-aware download request. Historical versions of this project
 * used `type=video|audio`; `quality` was already part of UnifiedDownloadOptions.
 * Passing the original page URL lets the backend select a fresh stream instead
 * of reusing a potentially low-resolution or IP-bound CDN URL.
 */
export function buildSourceMediaDownloadUrl({
    sourceUrl,
    type,
    quality,
    formatId,
}: {
    sourceUrl: string;
    type: MediaDownloadType;
    quality?: string | null;
    formatId?: number | null;
}): string {
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

    const separator = API_ENDPOINTS.unified.download.includes('?') ? '&' : '?';
    return `${API_ENDPOINTS.unified.download}${separator}${params.toString()}`;
}

type DownloadResolutionPayload = {
    success?: boolean;
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

/**
 * Galaxy Downloader has used two compatible `/api/download` behaviors over
 * time:
 * 1. a resolver endpoint that returns JSON containing a fresh media URL;
 * 2. a streaming proxy that returns the media body directly.
 *
 * Probe the request once so the frontend works with either deployment. For a
 * JSON resolver response we return its media URL; for a streaming response we
 * cancel the probe body and return the original API request URL so the browser
 * performs the real download without buffering the whole video in JS memory.
 */
export async function resolveSourceMediaDownloadUrl(requestUrl: string): Promise<string> {
    const response = await fetch(requestUrl, {
        method: 'GET',
        cache: 'no-store',
    });

    const contentType = response.headers.get('content-type')?.toLowerCase() || '';
    const looksJson = contentType.includes('application/json') || contentType.includes('+json');

    if (looksJson) {
        let payload: DownloadResolutionPayload | null = null;
        try {
            payload = await response.json() as DownloadResolutionPayload;
        } catch {
            throw new Error('Download resolver returned invalid JSON');
        }

        if (!response.ok || payload.success === false) {
            const message = typeof payload.error === 'string'
                ? payload.error
                : typeof payload.message === 'string'
                    ? payload.message
                    : `Download request failed (${response.status})`;
            throw new Error(message);
        }

        const resolvedUrl = extractResolvedDownloadUrl(payload);
        if (!resolvedUrl) {
            throw new Error('Download resolver did not return a media URL');
        }
        return resolvedUrl;
    }

    if (!response.ok) {
        void response.body?.cancel();
        throw new Error(`Download request failed (${response.status})`);
    }

    // Do not buffer potentially multi-gigabyte media into memory merely to
    // trigger a save. Abort the probe and let a normal browser navigation run
    // the same streaming endpoint as the real download.
    void response.body?.cancel();
    return requestUrl;
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
