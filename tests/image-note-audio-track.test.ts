import React from 'react'
import { describe, expect, test, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

vi.mock('next/image', () => ({
  default: ({ fill: _fill, unoptimized: _unoptimized, priority: _priority, ...props }: Record<string, unknown>) => React.createElement('img', props),
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
    history: {
      unknownTitle: '未知标题',
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

const imageNote = {
  title: '图文笔记',
  desc: 'desc',
  cover: 'https://img.example.com/cover.jpg',
  platform: 'douyin',
  url: 'https://www.douyin.com/note/7668207335739717491',
  kind: 'image' as const,
  noteType: 'image' as const,
  images: ['https://img.example.com/1.webp'],
  downloadVideoUrl: null,
  originDownloadVideoUrl: null,
}

function render(result: Record<string, unknown>) {
  return renderToStaticMarkup(
    React.createElement(ResultCard, {
      result: result as never,
      onClose: () => {},
      onOpenExtractAudio: () => {},
      onRequestPreview: () => {},
      onClearPreview: () => {},
    })
  )
}

describe('图文笔记的背景音轨', () => {
  test('后端给出音轨时应显示音频下载入口', () => {
    const html = render({
      ...imageNote,
      downloadAudioUrl: '/api/download?raw=1&type=audio',
      originDownloadAudioUrl: 'https://sf6-cdn-tos.douyinstatic.com/obj/ies-music/1.mp3',
      mediaActions: { video: 'hide', audio: 'direct-download' } as const,
    })

    expect(html).toContain('下载音频')
    expect(html).toContain('img.example.com%2F1.webp')
  })

  test('没有音轨时只显示图片，不出现音频入口', () => {
    const html = render({
      ...imageNote,
      downloadAudioUrl: null,
      originDownloadAudioUrl: null,
      mediaActions: { video: 'hide', audio: 'hide' } as const,
    })

    expect(html).not.toContain('下载音频')
    expect(html).toContain('img.example.com%2F1.webp')
  })
})
