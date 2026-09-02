import { NextRequest, NextResponse } from 'next/server'

import { fetchVimeoControlJson, fetchVimeoControlPage } from '@/lib/vimeo-control'
import type { UnifiedParseResult, VideoQualityOption } from '@/lib/types'

const USER_AGENT =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36'

const JSON_HEADERS = {
  Accept: 'application/json,text/plain,*/*',
  'Accept-Language': 'en-US,en;q=0.9',
  'User-Agent': USER_AGENT,
}

const HTML_HEADERS = {
  Accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
  'Accept-Language': 'en-US,en;q=0.9',
  'User-Agent': USER_AGENT,
}

type VimeoProgressive = {
  url?: string
  quality?: string
  width?: number
  height?: number
  fps?: number
  mime?: string
}

type VimeoCdn = { url?: string }

type VimeoFiles = {
  progressive?: VimeoProgressive[]
  hls?: {
    default_cdn?: string
    cdns?: Record<string, VimeoCdn>
  }
}

type VimeoConfig = {
  video?: {
    title?: string
    duration?: number
    thumbs?: Record<string, string>
    thumb?: string
    files?: VimeoFiles
  }
  request?: { files?: VimeoFiles }
}

type VimeoOEmbed = {
  title?: string
  thumbnail_url?: string
  duration?: number
  html?: string
}

function noStoreJson(payload: UnifiedParseResult, status = 200) {
  const response = NextResponse.json(payload, { status })
  response.headers.set('Cache-Control', 'no-store')
  response.headers.set('X-Robots-Tag', 'noindex, nofollow, noarchive')
  return response
}

function decodeHtml(value: string): string {
  return value
    .replace(/&amp;/g, '&')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\\u0026/gi, '&')
    .replace(/\\\//g, '/')
}

function extractBalancedJson(text: string, marker: RegExp): unknown | null {
  const match = marker.exec(text)
  if (!match) return null
  const start = text.indexOf('{', match.index + match[0].length)
  if (start < 0) return null

  let depth = 0
  let inString = false
  let escaped = false
  for (let index = start; index < text.length; index += 1) {
    const char = text[index]
    if (inString) {
      if (escaped) escaped = false
      else if (char === '\\') escaped = true
      else if (char === '"') inString = false
      continue
    }
    if (char === '"') {
      inString = true
      continue
    }
    if (char === '{') depth += 1
    else if (char === '}') {
      depth -= 1
      if (depth === 0) {
        try {
          return JSON.parse(text.slice(start, index + 1))
        } catch {
          return null
        }
      }
    }
  }
  return null
}

function parseSource(raw: string): { url: URL; id: string } | null {
  try {
    const url = new URL(raw)
    if (!/(^|\.)vimeo\.com$/i.test(url.hostname)) return null
    const id = url.pathname.match(/(?:video\/)?(\d{5,})/)?.[1]
    return id ? { url, id } : null
  } catch {
    return null
  }
}

function iframeSrc(html: string | undefined): string | null {
  if (!html) return null
  const value = html.match(/<iframe[^>]+src=["']([^"']+)["']/i)?.[1]
  return value ? decodeHtml(value) : null
}

async function getEmbed(id: string): Promise<{ embedUrl: string; oembed: VimeoOEmbed }> {
  const endpoint = new URL('https://vimeo.com/api/oembed.json')
  endpoint.searchParams.set('url', `https://vimeo.com/${id}`)
  const oembed = await fetchVimeoControlJson<VimeoOEmbed>(endpoint.toString(), {
    ...JSON_HEADERS,
    Referer: 'https://vimeo.com/',
  }, 'Vimeo oEmbed request')
  const src = iframeSrc(oembed.html)
  const fallback = `https://player.vimeo.com/video/${id}`
  if (!src) return { embedUrl: fallback, oembed }
  try {
    const embed = new URL(src)
    if (embed.hostname === 'player.vimeo.com' && embed.pathname.startsWith(`/video/${id}`)) {
      return { embedUrl: embed.toString(), oembed }
    }
  } catch {
    // Use canonical player URL below.
  }
  return { embedUrl: fallback, oembed }
}

async function fetchConfig(id: string): Promise<{ config: VimeoConfig; oembed: VimeoOEmbed }> {
  const { embedUrl, oembed } = await getEmbed(id)
  const page = await fetchVimeoControlPage(embedUrl, {
    ...HTML_HEADERS,
    Referer: `https://vimeo.com/${id}`,
  }, 'Vimeo player request')

  if (page.ok) {
    const html = page.text
    for (const marker of [/\bplayerConfig\s*=\s*/i, /\bvimeo\.config\s*=\s*/i, /\bconfig\s*=\s*/i]) {
      const value = extractBalancedJson(html, marker)
      if (value && typeof value === 'object') return { config: value as VimeoConfig, oembed }
    }
    const configValue = html.match(/\bdata-config-url=["']([^"']+)["']/i)?.[1]
      || html.match(/["']config_url["']\s*:\s*["']([^"']+)["']/i)?.[1]
    if (configValue) {
      const config = await fetchVimeoControlJson<VimeoConfig>(decodeHtml(configValue), {
        ...JSON_HEADERS,
        Referer: embedUrl,
        Origin: 'https://player.vimeo.com',
      }, 'Vimeo player config request')
      return { config, oembed }
    }
  }

  const configUrl = new URL(embedUrl)
  configUrl.pathname = `${configUrl.pathname.replace(/\/$/, '')}/config`
  const config = await fetchVimeoControlJson<VimeoConfig>(configUrl.toString(), {
    ...JSON_HEADERS,
    Referer: embedUrl,
    Origin: 'https://player.vimeo.com',
  }, 'Vimeo canonical config request')
  return { config, oembed }
}

function progressive(config: VimeoConfig): VimeoProgressive[] {
  return (config.video?.files?.progressive || config.request?.files?.progressive || [])
    .filter((item) => typeof item.url === 'string' && item.url.length > 0)
    .sort((a, b) => (b.height || 0) - (a.height || 0))
}

function hlsUrl(config: VimeoConfig): string | null {
  const hls = config.request?.files?.hls || config.video?.files?.hls
  if (!hls?.cdns) return null
  const preferred = hls.default_cdn ? hls.cdns[hls.default_cdn]?.url : undefined
  if (preferred) return preferred
  return Object.values(hls.cdns).find((item) => typeof item?.url === 'string' && item.url.length > 0)?.url || null
}

function highestThumb(thumbs?: Record<string, string>): string | null {
  if (!thumbs) return null
  return Object.entries(thumbs)
    .filter(([, value]) => typeof value === 'string' && value.length > 0)
    .sort(([a], [b]) => Number(b) - Number(a))[0]?.[1] || null
}

function mediaUrl(params: Record<string, string>) {
  const query = new URLSearchParams(params)
  return `/api/vimeo-media?${query.toString()}`
}

export async function GET(request: NextRequest) {
  const raw = request.nextUrl.searchParams.get('url')?.trim() || ''
  const source = parseSource(raw)
  if (!source) {
    return noStoreJson({ success: false, code: 'BAD_REQUEST', status: 400, error: 'Invalid Vimeo URL' }, 400)
  }

  try {
    const { config, oembed } = await fetchConfig(source.id)
    const formats = progressive(config)
    const hls = hlsUrl(config)

    const qualityOptions: VideoQualityOption[] = formats.map((format, index) => {
      const height = format.height || Number.parseInt(format.quality || '', 10) || undefined
      return {
        quality: height ? String(height) : format.quality || String(index),
        label: height ? `${height}p` : format.quality || 'MP4',
        width: format.width,
        height,
        fps: format.fps,
        ext: 'mp4',
        downloadUrl: mediaUrl({ id: source.id, mode: 'progressive', quality: height ? String(height) : format.quality || 'best' }),
      }
    })

    const progressiveBest = qualityOptions[0]?.downloadUrl || null
    const hlsProxy = hls ? mediaUrl({ id: source.id, mode: 'hls' }) : null
    const best = progressiveBest || hlsProxy
    if (!best) {
      return noStoreJson({
        success: false,
        code: 'UPSTREAM_ERROR',
        status: 502,
        error: 'Vimeo player config did not expose a downloadable MP4 or HLS stream',
      }, 502)
    }

    const payload: UnifiedParseResult = {
      success: true,
      data: {
        title: config.video?.title || oembed.title || `Vimeo ${source.id}`,
        cover: highestThumb(config.video?.thumbs) || config.video?.thumb || oembed.thumbnail_url || null,
        platform: 'vimeo',
        downloadAudioUrl: null,
        downloadVideoUrl: best,
        originDownloadAudioUrl: null,
        originDownloadVideoUrl: best,
        videoAudioMode: 'muxed',
        mediaActions: {
          video: progressiveBest ? 'direct-download' : 'browser-hls-download',
          audio: 'extract-audio',
        },
        qualityOptions,
        url: source.url.toString(),
        duration: config.video?.duration || oembed.duration,
        kind: 'video',
      },
    }
    return noStoreJson(payload)
  } catch (error) {
    return noStoreJson({
      success: false,
      code: 'UPSTREAM_ERROR',
      status: 502,
      error: error instanceof Error ? error.message : 'Vimeo native parser failed',
    }, 502)
  }
}
