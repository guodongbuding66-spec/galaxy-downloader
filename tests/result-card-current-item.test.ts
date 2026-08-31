import React from 'react'
import { describe, expect, test, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

vi.mock('next/image', () => ({
  default: (props: Record<string, unknown>) => React.createElement('img', props),
}))

vi.mock('@/i18n/client', () => ({
  useDictionary: () => ({
    result: {
      title: 'Result',
      totalParts: '分P {count}',
      videoCount: '合集 {count}',
      videoList: '合集列表',
      collectionSearchPlaceholder: '搜索合集',
      collectionNoSearchResults: '无结果',
      articleVideoUntitled: '视频 {index}',
      playVideo: '播放视频',
      playAudio: '播放音频',
      downloadVideo: '下载视频',
      downloadAudio: '下载音频',
      mergeDownloadVideo: '合并下载视频',
      mergeDownloadVideoHint: 'hint',
      pureMusicHint: 'audio hint',
      originDownloadVideo: '原始视频',
      originDownloadAudio: '原始音频',
      sharePlayLink: '分享',
      sharePlayLinkCopied: '已复制',
      coverLabel: '封面',
      imageNote: '图片',
      imageCount: '{count} 张',
      imageLoadingProgress: '{loaded}/{total}',
      packaging: '打包中',
      packageDownload: '打包下载',
      loading: '加载中',
      downloadImage: '下载图片',
      downloadCover: '下载封面',
      imageAlt: '图片 {index}',
      imageIndexLabel: '图片 {index}',
      previewPlayerTitle: '预览',
      loadFailed: '失败',
      loadMoreItems: '更多 {count}',
      collapseParts: '收起 {count}',
    },
    extractAudio: {
      button: '提取音频',
    },
    errors: {
      clipboardFailed: '复制失败',
      clipboardPermission: '无权限',
      downloadError: '下载失败',
      allImagesLoadFailed: '图片加载失败',
      packageFailed: '打包失败',
    },
  }),
}))

vi.mock('@/lib/deferred-toast', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}))

vi.mock('@/components/ui/button', () => ({
  Button: ({ children, asChild, ...props }: Record<string, unknown> & { children?: React.ReactNode; asChild?: boolean }) => {
    if (asChild && React.isValidElement(children)) {
      return React.cloneElement(children, props)
    }

    return React.createElement('button', props, children)
  },
}))

vi.mock('@/components/ui/card', () => ({
  Card: ({ children, ...props }: Record<string, unknown> & { children?: React.ReactNode }) => React.createElement('div', props, children),
  CardContent: ({ children, ...props }: Record<string, unknown> & { children?: React.ReactNode }) => React.createElement('div', props, children),
  CardHeader: ({ children, ...props }: Record<string, unknown> & { children?: React.ReactNode }) => React.createElement('div', props, children),
  CardTitle: ({ children, ...props }: Record<string, unknown> & { children?: React.ReactNode }) => React.createElement('div', props, children),
}))

vi.mock('@/components/ui/input', () => ({
  Input: (props: Record<string, unknown>) => React.createElement('input', props),
}))

import { ResultCard } from '../src/components/downloader/ResultCard'

describe('ResultCard current collection item highlighting', () => {
  test('合集列表应高亮 currentItemId 对应的视频项', () => {
    const result = {
      title: '测试合集',
      desc: 'desc',
      cover: 'https://img.example.com/cover.jpg',
      platform: 'bili',
      url: 'https://www.bilibili.com/video/BV1ab411c7nA/',
      downloadAudioUrl: '/api/download?type=audio&item=BV2',
      downloadVideoUrl: '/api/download?type=video&item=BV2',
      originDownloadAudioUrl: null,
      originDownloadVideoUrl: null,
      mediaActions: { video: 'direct-download', audio: 'direct-download' } as const,
      duration: 123,
      isMultiPart: false,
      currentItemId: 'BV2',
      videos: [
        {
          id: 'BV1',
          title: '合集第1集',
          duration: 111,
          downloadVideoUrl: '/api/download?type=video&item=BV1',
          downloadAudioUrl: '/api/download?type=audio&item=BV1',
        },
        {
          id: 'BV2',
          title: '合集第2集当前页',
          duration: 123,
          downloadVideoUrl: '/api/download?type=video&item=BV2',
          downloadAudioUrl: '/api/download?type=audio&item=BV2',
        },
      ],
    }

    const html = renderToStaticMarkup(
      React.createElement(ResultCard, {
        result,
        onClose: () => {},
        onOpenExtractAudio: () => {},
        onRequestPreview: () => {},
        onClearPreview: () => {},
      })
    )

    expect(html).toContain('合集第2集当前页')
    expect(html).toContain('border-primary bg-primary/5')
    expect(html).not.toContain('<video')
    expect(html).not.toContain('/api/play?url=')
    expect(html).toContain('<img')
    expect(html.match(/aria-label="播放视频"/g) ?? []).toHaveLength(1)
    expect(html.match(/aria-label="播放音频"/g) ?? []).toHaveLength(1)
    expect(html).toMatch(/aria-label="播放视频: 合集第1集"/)
    expect(html).toMatch(/aria-label="播放音频: 合集第1集"/)
    expect(html).toMatch(/aria-label="播放视频: 合集第2集当前页"/)
    expect(html).toMatch(/aria-label="播放音频: 合集第2集当前页"/)
  })

  test('B站合集返回 kind: picker 但没有 episodes 时仍渲染合集列表', () => {
    const result = {
      title: '测试合集',
      cover: 'https://img.example.com/cover.jpg',
      platform: 'bili',
      url: 'https://www.bilibili.com/video/BV1ab411c7nA/',
      kind: 'picker' as const,
      downloadAudioUrl: '/api/download?type=audio&item=BV2',
      downloadVideoUrl: '/api/download?type=video&item=BV2',
      originDownloadAudioUrl: null,
      originDownloadVideoUrl: null,
      mediaActions: { video: 'direct-download', audio: 'direct-download' } as const,
      duration: 123,
      isMultiPart: false,
      currentItemId: 'BV2',
      videos: [
        {
          id: 'BV1',
          title: '合集第1集',
          duration: 111,
          downloadVideoUrl: '/api/download?type=video&item=BV1',
          downloadAudioUrl: '/api/download?type=audio&item=BV1',
        },
        {
          id: 'BV2',
          title: '合集第2集当前页',
          duration: 123,
          downloadVideoUrl: '/api/download?type=video&item=BV2',
          downloadAudioUrl: '/api/download?type=audio&item=BV2',
        },
      ],
    }

    const html = renderToStaticMarkup(
      React.createElement(ResultCard, {
        result,
        onClose: () => {},
        onOpenExtractAudio: () => {},
        onRequestPreview: () => {},
        onClearPreview: () => {},
      })
    )

    expect(html).toContain('合集第1集')
    expect(html).toContain('合集第2集当前页')
    expect(html).toContain('border-primary bg-primary/5')
  })

  test('同时包含分P和合集时默认显示分P并统一提供四种文字操作', () => {
    const result = {
      title: '双形态视频',
      cover: 'https://img.example.com/cover.jpg',
      platform: 'bili',
      url: 'https://www.bilibili.com/video/BV-source/',
      kind: 'picker' as const,
      downloadAudioUrl: '/api/download?type=audio&item=1',
      downloadVideoUrl: '/api/download?type=video&item=1',
      originDownloadAudioUrl: null,
      originDownloadVideoUrl: null,
      videoAudioMode: 'muxed' as const,
      mediaActions: { video: 'direct-download', audio: 'direct-download' } as const,
      isMultiPart: true,
      currentPage: 1,
      currentItemId: 'BV-source',
      pages: [
        {
          page: 1,
          cid: 'cid-1',
          part: 'P1 正片',
          duration: 120,
          downloadVideoUrl: '/api/download?type=video&item=1',
          downloadAudioUrl: '/api/download?type=audio&item=1',
          videoAudioMode: 'muxed' as const,
        },
        {
          page: 2,
          cid: 'cid-2',
          part: 'P2 花絮',
          duration: 60,
          downloadVideoUrl: '/api/download?type=video&item=2',
          downloadAudioUrl: '/api/download?type=audio&item=2',
        },
      ],
      videos: [
        {
          id: 'BV-season-1',
          title: '合集第1集',
          downloadVideoUrl: '/api/download?type=video&item=BV-season-1',
          downloadAudioUrl: '/api/download?type=audio&item=BV-season-1',
        },
        {
          id: 'BV-source',
          title: '合集当前集',
          downloadVideoUrl: '/api/download?type=video&item=BV-source',
          downloadAudioUrl: '/api/download?type=audio&item=BV-source',
        },
      ],
    }

    const html = renderToStaticMarkup(
      React.createElement(ResultCard, {
        result,
        onClose: () => {},
        onOpenExtractAudio: () => {},
        onRequestPreview: () => {},
        onClearPreview: () => {},
      })
    )

    expect(html).toContain('P1 正片')
    expect(html).toContain('P2 花絮')
    expect(html).not.toContain('合集当前集')
    expect(html).not.toContain('role="button"')
    expect(html).toMatch(/aria-label="播放视频: P1 正片"/)
    expect(html).toMatch(/aria-label="播放音频: P1 正片"/)
    expect(html).toMatch(/aria-label="下载视频: P1 正片"/)
    expect(html).toMatch(/aria-label="下载音频: P1 正片"/)
    expect(html).toContain('border-primary bg-primary/5')
  })

  test('纯音频单流结果默认显示封面和单独的播放音频按钮', () => {
    const result = {
      title: '测试音频',
      desc: 'audio only',
      cover: 'https://img.example.com/audio-cover.jpg',
      platform: 'soundcloud',
      url: 'https://soundcloud.com/example/track',
      downloadAudioUrl: 'https://cdn.example.com/audio.mp3',
      downloadVideoUrl: null,
      originDownloadAudioUrl: null,
      originDownloadVideoUrl: null,
      mediaActions: { video: 'hide', audio: 'direct-download' } as const,
      noteType: 'audio' as const,
    }

    const html = renderToStaticMarkup(
      React.createElement(ResultCard, {
        result,
        onClose: () => {},
        onOpenExtractAudio: () => {},
        onRequestPreview: () => {},
        onClearPreview: () => {},
      })
    )

    expect(html).not.toContain('<audio')
    expect(html).toContain('<img')
    expect(html).toContain('>分享<')
    expect(html.match(/aria-label="播放视频"/g) ?? []).toHaveLength(0)
    expect(html.match(/aria-label="播放音频"/g) ?? []).toHaveLength(1)
  })

  test('muxed 单流结果默认显示封面和单独的播放视频按钮', () => {
    const result = {
      title: '测试视频',
      desc: 'muxed video',
      cover: 'https://img.example.com/video-cover.jpg',
      platform: 'bili',
      url: 'https://www.bilibili.com/video/BV1muxed/',
      downloadAudioUrl: null,
      downloadVideoUrl: 'https://cdn.example.com/video.mp4',
      originDownloadAudioUrl: null,
      originDownloadVideoUrl: null,
      videoAudioMode: 'muxed' as const,
      mediaActions: { video: 'direct-download', audio: 'extract-audio' } as const,
    }

    const html = renderToStaticMarkup(
      React.createElement(ResultCard, {
        result,
        onClose: () => {},
        onOpenExtractAudio: () => {},
        onRequestPreview: () => {},
        onClearPreview: () => {},
      })
    )

    expect(html).not.toContain('<video')
    expect(html).toContain('<img')
    expect(html).toContain('>分享<')
    expect(html.match(/aria-label="播放视频"/g) ?? []).toHaveLength(1)
    expect(html.match(/aria-label="播放音频"/g) ?? []).toHaveLength(0)
  })

  test('用户选择视频播放后才渲染播放器', () => {
    const result = {
      title: '测试视频',
      cover: 'https://img.example.com/video-cover.jpg',
      platform: 'bili',
      url: 'https://www.bilibili.com/video/BV1muxed/',
      downloadAudioUrl: null,
      downloadVideoUrl: 'https://cdn.example.com/video.mp4',
      originDownloadAudioUrl: null,
      originDownloadVideoUrl: null,
      videoAudioMode: 'muxed' as const,
      mediaActions: { video: 'direct-download', audio: 'extract-audio' } as const,
    }

    const html = renderToStaticMarkup(
      React.createElement(ResultCard, {
        result,
        onClose: () => {},
        onOpenExtractAudio: () => {},
        onRequestPreview: () => {},
        onClearPreview: () => {},
        activePreview: {
          mediaType: 'video',
          sourceUrl: result.url,
          title: result.title,
          autoplay: true,
        },
      })
    )

    expect(html).toContain('<video')
    expect(html).toContain('/api/download?url=')
    expect(html).toContain('autoPlay=""')
  })
})