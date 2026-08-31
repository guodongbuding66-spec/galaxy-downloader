import { API_ENDPOINTS } from '@/lib/config'
import type { EmbeddedVideoInfo, PageInfo, PodcastEpisodeInfo, UnifiedParseResult } from '@/lib/types'

import { getResultMediaActions, hasSourceUrl, shouldShowVideoDownloadButton } from './result-card-visibility'

export type PreviewMediaType = 'video' | 'audio'

export interface MediaPreviewRequest {
    mediaType: PreviewMediaType
    sourceUrl: string
    /**
     * Exact media URL returned by the parser. Local Engine URLs are normally
     * signed for the user's own IP/browser and should be played directly rather
     * than asking a remote backend to resolve the source URL again.
     */
    directUrl?: string | null
    title: string
    item?: string
    autoplay?: boolean
    origin?: 'share' | 'result' | 'user'
}

type ParsedResultData = NonNullable<UnifiedParseResult['data']>

function usableDirectUrl(value?: string | null): string | null {
    const url = value?.trim()
    if (!url) return null
    // Generated /api/download URLs are download jobs, not lightweight preview
    // streams. Let the source-aware play endpoint handle those instead.
    if (/\/api\/download(?:\?|$)/i.test(url)) return null
    if (url.startsWith('/') || /^https?:\/\//i.test(url)) return url
    return null
}

export function buildMediaPreviewUrl(request: MediaPreviewRequest): string {
    const direct = usableDirectUrl(request.directUrl)
    if (direct) return direct

    const params = new URLSearchParams({
        url: request.sourceUrl,
        type: request.mediaType,
    })

    if (request.item) {
        params.set('item', request.item)
    }

    return `${API_ENDPOINTS.unified.play}?${params.toString()}`
}

export function canPreviewResultVideo(result: ParsedResultData): boolean {
    const videoDownloadUrl = result.downloadVideoUrl || result.originDownloadVideoUrl || null
    const audioDownloadUrl = result.downloadAudioUrl || result.originDownloadAudioUrl || null
    const { videoAction } = getResultMediaActions({
        videoAudioMode: result.videoAudioMode,
        videoDownloadUrl,
        audioDownloadUrl,
        originDownloadVideoUrl: result.originDownloadVideoUrl,
        originDownloadAudioUrl: result.originDownloadAudioUrl,
        mediaActions: result.mediaActions,
    })

    return (videoAction === 'direct-download' || videoAction === 'browser-hls-download')
        && shouldShowVideoDownloadButton(videoDownloadUrl)
}

export function canPreviewResultAudio(result: ParsedResultData): boolean {
    const videoDownloadUrl = result.downloadVideoUrl || result.originDownloadVideoUrl || null
    const audioDownloadUrl = result.downloadAudioUrl || result.originDownloadAudioUrl || null
    const { audioAction } = getResultMediaActions({
        videoAudioMode: result.videoAudioMode,
        videoDownloadUrl,
        audioDownloadUrl,
        originDownloadVideoUrl: result.originDownloadVideoUrl,
        originDownloadAudioUrl: result.originDownloadAudioUrl,
        mediaActions: result.mediaActions,
    })

    return audioAction === 'direct-download' && hasSourceUrl(audioDownloadUrl)
}

export function canSharePlayResult(result: ParsedResultData): boolean {
    return canPreviewResultVideo(result) || canPreviewResultAudio(result)
}

export function buildPrimaryResultPreview(
    result: ParsedResultData,
    options: {
        autoplay?: boolean
        preferAudio?: boolean
    } = {}
): MediaPreviewRequest | null {
    const sourceUrl = result.url.trim()
    if (!sourceUrl) {
        return null
    }

    const mediaTypes: PreviewMediaType[] = options.preferAudio
        ? ['audio', 'video']
        : ['video', 'audio']

    for (const mediaType of mediaTypes) {
        if (mediaType === 'video' && canPreviewResultVideo(result)) {
            return {
                mediaType,
                sourceUrl,
                directUrl: result.downloadVideoUrl || result.originDownloadVideoUrl || null,
                title: result.title,
                autoplay: options.autoplay,
            }
        }

        if (mediaType === 'audio' && canPreviewResultAudio(result)) {
            return {
                mediaType,
                sourceUrl,
                directUrl: result.downloadAudioUrl || result.originDownloadAudioUrl || null,
                title: result.title,
                autoplay: options.autoplay,
            }
        }
    }

    return null
}

export function buildPagePreview(
    sourceUrl: string,
    page: PageInfo,
    options: {
        autoplay?: boolean
        preferAudio?: boolean
    } = {}
): MediaPreviewRequest | null {
    if (!sourceUrl.trim()) {
        return null
    }

    const mediaTypes: PreviewMediaType[] = options.preferAudio
        ? ['audio', 'video']
        : ['video', 'audio']

    for (const mediaType of mediaTypes) {
        if (mediaType === 'video' && canPreviewPageVideo(page)) {
            return {
                mediaType,
                sourceUrl,
                directUrl: page.downloadVideoUrl,
                title: page.part,
                item: String(page.page),
                autoplay: options.autoplay,
            }
        }

        if (mediaType === 'audio' && canPreviewPageAudio(page)) {
            return {
                mediaType,
                sourceUrl,
                directUrl: page.downloadAudioUrl,
                title: page.part,
                item: String(page.page),
                autoplay: options.autoplay,
            }
        }
    }

    return null
}

export function buildEmbeddedVideoPreview(
    sourceUrl: string,
    video: EmbeddedVideoInfo,
    options: {
        autoplay?: boolean
        preferAudio?: boolean
    } = {}
): MediaPreviewRequest | null {
    if (!sourceUrl.trim()) {
        return null
    }

    const mediaTypes: PreviewMediaType[] = options.preferAudio
        ? ['audio', 'video']
        : ['video', 'audio']

    for (const mediaType of mediaTypes) {
        if (mediaType === 'video' && canPreviewEmbeddedVideoVideo(video)) {
            return {
                mediaType,
                sourceUrl,
                directUrl: video.downloadVideoUrl || video.originDownloadVideoUrl || null,
                title: video.title,
                item: video.id,
                autoplay: options.autoplay,
            }
        }

        if (mediaType === 'audio' && canPreviewEmbeddedVideoAudio(video)) {
            return {
                mediaType,
                sourceUrl,
                directUrl: video.downloadAudioUrl || video.originDownloadAudioUrl || null,
                title: video.title,
                item: video.id,
                autoplay: options.autoplay,
            }
        }
    }

    return null
}

export function canPreviewPageVideo(page: PageInfo): boolean {
    const { videoAction } = getResultMediaActions({
        videoAudioMode: page.videoAudioMode,
        videoDownloadUrl: page.downloadVideoUrl,
        audioDownloadUrl: page.downloadAudioUrl,
    })

    return videoAction === 'direct-download' && shouldShowVideoDownloadButton(page.downloadVideoUrl)
}

export function canPreviewPageAudio(page: PageInfo): boolean {
    const { audioAction } = getResultMediaActions({
        videoAudioMode: page.videoAudioMode,
        videoDownloadUrl: page.downloadVideoUrl,
        audioDownloadUrl: page.downloadAudioUrl,
    })

    return audioAction === 'direct-download' && hasSourceUrl(page.downloadAudioUrl)
}

export function canPreviewEmbeddedVideoVideo(video: EmbeddedVideoInfo): boolean {
    const videoDownloadUrl = video.downloadVideoUrl || video.originDownloadVideoUrl || null
    const audioDownloadUrl = video.downloadAudioUrl || video.originDownloadAudioUrl || null
    const { videoAction } = getResultMediaActions({
        videoAudioMode: video.videoAudioMode,
        videoDownloadUrl,
        audioDownloadUrl,
        originDownloadVideoUrl: video.originDownloadVideoUrl,
        originDownloadAudioUrl: video.originDownloadAudioUrl,
        mediaActions: video.mediaActions,
    })

    return videoAction === 'direct-download' && shouldShowVideoDownloadButton(videoDownloadUrl)
}

export function canPreviewEpisodeAudio(episode: PodcastEpisodeInfo): boolean {
    const audioUrl = episode.downloadAudioUrl || episode.originDownloadAudioUrl
    return typeof audioUrl === 'string' && audioUrl.trim().length > 0
}

export function buildEpisodePreview(
    sourceUrl: string,
    episode: PodcastEpisodeInfo,
    options: { autoplay?: boolean } = {}
): MediaPreviewRequest | null {
    if (!sourceUrl.trim() || !canPreviewEpisodeAudio(episode)) {
        return null
    }

    return {
        mediaType: 'audio',
        sourceUrl,
        directUrl: episode.downloadAudioUrl || episode.originDownloadAudioUrl || null,
        title: episode.title,
        item: episode.id,
        autoplay: options.autoplay,
    }
}

export function canPreviewEmbeddedVideoAudio(video: EmbeddedVideoInfo): boolean {
    const videoDownloadUrl = video.downloadVideoUrl || video.originDownloadVideoUrl || null
    const audioDownloadUrl = video.downloadAudioUrl || video.originDownloadAudioUrl || null
    const { audioAction } = getResultMediaActions({
        videoAudioMode: video.videoAudioMode,
        videoDownloadUrl,
        audioDownloadUrl,
        originDownloadVideoUrl: video.originDownloadVideoUrl,
        originDownloadAudioUrl: video.originDownloadAudioUrl,
        mediaActions: video.mediaActions,
    })

    return audioAction === 'direct-download' && hasSourceUrl(audioDownloadUrl)
}

export function buildResultPreviewForSelection(
    result: ParsedResultData,
    options: {
        item?: string
        mediaType?: PreviewMediaType
        autoplay?: boolean
    } = {}
): MediaPreviewRequest | null {
    const sourceUrl = result.url.trim()
    if (!sourceUrl) {
        return null
    }

    const buildExactPreview = (
        mediaType: PreviewMediaType,
        title: string,
        item: string | undefined,
        canPreview: boolean,
        directUrl?: string | null,
    ): MediaPreviewRequest | null => canPreview
        ? {
              mediaType,
              sourceUrl,
              directUrl,
              title,
              item,
              autoplay: options.autoplay,
          }
        : null

    if (options.item) {
        const page = result.pages?.find((candidate) => String(candidate.page) === options.item)
        if (page) {
            if (!options.mediaType) {
                return buildPagePreview(sourceUrl, page, { autoplay: options.autoplay })
            }

            return buildExactPreview(
                options.mediaType,
                page.part,
                String(page.page),
                options.mediaType === 'video' ? canPreviewPageVideo(page) : canPreviewPageAudio(page),
                options.mediaType === 'video' ? page.downloadVideoUrl : page.downloadAudioUrl,
            )
        }

        const video = result.videos?.find((candidate) => candidate.id === options.item)
        if (video) {
            if (!options.mediaType) {
                return buildEmbeddedVideoPreview(sourceUrl, video, { autoplay: options.autoplay })
            }

            return buildExactPreview(
                options.mediaType,
                video.title,
                video.id,
                options.mediaType === 'video'
                    ? canPreviewEmbeddedVideoVideo(video)
                    : canPreviewEmbeddedVideoAudio(video),
                options.mediaType === 'video'
                    ? video.downloadVideoUrl || video.originDownloadVideoUrl
                    : video.downloadAudioUrl || video.originDownloadAudioUrl,
            )
        }

        const episode = result.episodes?.find((candidate) => candidate.id === options.item)
        if (episode) {
            if (options.mediaType && options.mediaType !== 'audio') {
                return null
            }

            return buildEpisodePreview(sourceUrl, episode, { autoplay: options.autoplay })
        }

        return null
    }

    if (!options.mediaType) {
        return buildPrimaryResultPreview(result, { autoplay: options.autoplay })
    }

    return buildExactPreview(
        options.mediaType,
        result.title,
        undefined,
        options.mediaType === 'video' ? canPreviewResultVideo(result) : canPreviewResultAudio(result),
        options.mediaType === 'video'
            ? result.downloadVideoUrl || result.originDownloadVideoUrl
            : result.downloadAudioUrl || result.originDownloadAudioUrl,
    )
}
