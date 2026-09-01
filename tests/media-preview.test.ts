import { describe, expect, it } from 'vitest'

import {
    buildEmbeddedVideoPreview,
    buildMediaPreviewUrl,
    buildPagePreview,
    buildPrimaryResultPreview,
    buildResultPreviewForSelection,
    canPreviewEmbeddedVideoAudio,
    canPreviewEmbeddedVideoVideo,
    canPreviewPageAudio,
    canPreviewPageVideo,
    canPreviewResultAudio,
    canPreviewResultVideo,
    canSharePlayResult,
} from '../src/components/downloader/media-preview.ts'

describe('media preview helpers', () => {
it('keeps share play enabled for audio-only results', () => {
    const result = {
        title: 'Audio only',
        platform: 'soundcloud',
        url: 'https://soundcloud.com/example/track',
        downloadAudioUrl: 'https://cdn.example.com/audio.mp3',
        downloadVideoUrl: null,
        originDownloadAudioUrl: null,
        originDownloadVideoUrl: null,
        mediaActions: {
            video: 'hide',
            audio: 'direct-download',
        } as const,
    }

    expect(canPreviewResultVideo(result)).toBe(false)
    expect(canPreviewResultAudio(result)).toBe(true)
    expect(canSharePlayResult(result)).toBe(true)
    expect(buildPrimaryResultPreview(result)).toEqual({
        mediaType: 'audio',
        sourceUrl: 'https://soundcloud.com/example/track',
        directUrl: 'https://cdn.example.com/audio.mp3',
        title: 'Audio only',
        autoplay: undefined,
    })
})

it('keeps share play enabled for muxed video results without a separate audio stream', () => {
    const result = {
        title: 'Muxed video',
        platform: 'bili',
        url: 'https://www.bilibili.com/video/BV1muxed/',
        downloadAudioUrl: null,
        downloadVideoUrl: 'https://cdn.example.com/video.mp4',
        originDownloadAudioUrl: null,
        originDownloadVideoUrl: null,
        videoAudioMode: 'muxed' as const,
    }

    expect(canPreviewResultVideo(result)).toBe(true)
    expect(canPreviewResultAudio(result)).toBe(false)
    expect(canSharePlayResult(result)).toBe(true)
    expect(buildPrimaryResultPreview(result)).toEqual({
        mediaType: 'video',
        sourceUrl: 'https://www.bilibili.com/video/BV1muxed/',
        directUrl: 'https://cdn.example.com/video.mp4',
        title: 'Muxed video',
        autoplay: undefined,
    })
})

it('plays exact parser URLs directly but never treats a download job itself as a preview stream', () => {
    expect(buildMediaPreviewUrl({
        mediaType: 'video',
        sourceUrl: 'https://www.instagram.com/reel/demo/',
        directUrl: 'https://scontent.example.net/signed-video.mp4?token=abc',
        title: 'Instagram reel',
    })).toBe('https://scontent.example.net/signed-video.mp4?token=abc')

    const fallback = buildMediaPreviewUrl({
        mediaType: 'video',
        sourceUrl: 'https://example.com/watch/1',
        directUrl: '/api/download?type=video',
        title: 'Remote download job',
    })
    expect(fallback).not.toBe('/api/download?type=video')
    expect(fallback).toContain('url=')
    expect(fallback).toContain('type=video')
})

it('builds an audio preview for a collection item when audio is preferred', () => {
    const video = {
        id: 'BV1audio',
        title: 'Collection item',
        downloadVideoUrl: '/api/download?type=video&item=BV1audio',
        downloadAudioUrl: '/api/download?type=audio&item=BV1audio',
    }

    expect(buildEmbeddedVideoPreview(
        'https://www.bilibili.com/video/BV1audio/',
        video,
        { autoplay: true, preferAudio: true }
    )).toEqual({
        mediaType: 'audio',
        sourceUrl: 'https://www.bilibili.com/video/BV1audio/',
        directUrl: '/api/download?type=audio&item=BV1audio',
        title: 'Collection item',
        item: 'BV1audio',
        autoplay: true,
    })
})

it('uses the same media capability resolver for pages and collection videos', () => {
    const separatePage = {
        page: 2,
        cid: 'cid-2',
        part: 'Separate page',
        duration: 20,
        downloadVideoUrl: '/api/download?type=video&item=2',
        downloadAudioUrl: '/api/download?type=audio&item=2',
        videoAudioMode: 'separate' as const,
    }
    const separateVideo = {
        id: 'BV-separate',
        title: 'Separate collection item',
        downloadVideoUrl: '/api/download?type=video&item=BV-separate',
        downloadAudioUrl: '/api/download?type=audio&item=BV-separate',
        videoAudioMode: 'separate' as const,
    }

    expect(canPreviewPageVideo(separatePage)).toBe(false)
    expect(canPreviewPageAudio(separatePage)).toBe(true)
    expect(canPreviewEmbeddedVideoVideo(separateVideo)).toBe(false)
    expect(canPreviewEmbeddedVideoAudio(separateVideo)).toBe(true)
    expect(buildPagePreview('https://www.bilibili.com/video/BV-pages/', separatePage)).toMatchObject({
        mediaType: 'audio',
        directUrl: '/api/download?type=audio&item=2',
        item: '2',
    })
})

it('keeps unknown item modes usable when both validated stream urls exist', () => {
    const page = {
        page: 3,
        cid: 'cid-3',
        part: 'Legacy page',
        duration: 30,
        downloadVideoUrl: '/api/download?type=video&item=3',
        downloadAudioUrl: '/api/download?type=audio&item=3',
    }

    expect(canPreviewPageVideo(page)).toBe(true)
    expect(canPreviewPageAudio(page)).toBe(true)
})

it('resolves an explicitly shared item and never falls back to another media type', () => {
    const result = {
        title: 'Multipart result',
        platform: 'bili',
        url: 'https://www.bilibili.com/video/BV-pages/',
        downloadAudioUrl: null,
        downloadVideoUrl: '/api/download?type=video',
        originDownloadAudioUrl: null,
        originDownloadVideoUrl: null,
        pages: [{
            page: 2,
            cid: 'cid-2',
            part: 'Audio-capable page',
            duration: 20,
            downloadVideoUrl: '/api/download?type=video&item=2',
            downloadAudioUrl: '/api/download?type=audio&item=2',
            videoAudioMode: 'separate' as const,
        }],
    }

    expect(buildResultPreviewForSelection(result, {
        item: '2',
        mediaType: 'audio',
        autoplay: true,
    })).toEqual({
        mediaType: 'audio',
        sourceUrl: result.url,
        directUrl: '/api/download?type=audio&item=2',
        title: 'Audio-capable page',
        item: '2',
        autoplay: true,
    })
    expect(buildResultPreviewForSelection(result, {
        item: '2',
        mediaType: 'video',
    })).toBeNull()
    expect(buildResultPreviewForSelection(result, {
        item: 'missing',
        mediaType: 'audio',
    })).toBeNull()
})
})