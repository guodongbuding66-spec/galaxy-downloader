import { NextRequest, NextResponse } from 'next/server'

import { fetchVimeoControlJson, fetchVimeoControlPage } from '@/lib/vimeo-control'

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

const ALLOWED_MEDIA_SUFFIXES = [
  'vimeo.com',
  'vimeocdn.com',
  'akamaized.net',
  'cloudfront.net',
]

type VimeoProgressive = {
  url?: string
  quality?: string
  height?: number
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
  video?: { files?: VimeoFiles }
  request?: { files?: VimeoFiles }
}

type VimeoOEmbed = { html?: string }

type ResolvedMedia = {
  url: string
  referer: string
  filename: string
}

function failure(message: string, status: number) {
  const response = NextResponse.json({ success: false, status, error: message }, { status })
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

function iframeSrc(html: string | undefined): string | null {
  if (!html) return null
  const value = html.match(/<iframe[^>]+src=["']([^"']+)["']/i)?.[1]
  return value ? decodeHtml(value) : null
}

async function getEmbedUrl(id: string): Promise<string> {
  const endpoint = new URL('https://vimeo.com/api/oembed.json')
  endpoint.searchParams.set('url', `https://vimeo.com/${id}`)
  const payload = await fetchVimeoControlJson<VimeoOEmbed>(endpoint.toString(), {
    ...JSON_HEADERS,
    Referer: 'https://vimeo.com/',
  }, 'Vimeo oEmbed request')
  const src = iframeSrc(payload.html)
  if (src) {
    try {
      const embed = new URL(src)
      if (embed.hostname === 'player.vimeo.com' && embed.pathname.startsWith(`/video/${id}`)) {
        return embed.toString()
      }
    } catch {
      // Fall through to the canonical player URL.
    }
  }
  return `https://player.vimeo.com/video/${id}`
}

async function fetchConfig(id: string): Promise<{ config: VimeoConfig; embedUrl: string }> {
  const embedUrl = await getEmbedUrl(id)
  const page = await fetchVimeoControlPage(embedUrl, {
    ...HTML_HEADERS,
    Referer: `https://vimeo.com/${id}`,
  }, 'Vimeo player request')

  if (page.ok) {
    const html = page.text
    for (const marker of [/\bplayerConfig\s*=\s*/i, /\bvimeo\.config\s*=\s*/i, /\bconfig\s*=\s*/i]) {
      const value = extractBalancedJson(html, marker)
      if (value && typeof value === 'object') return { config: value as VimeoConfig, embedUrl }
    }
    const configValue = html.match(/\bdata-config-url=["']([^"']+)["']/i)?.[1]
      || html.match(/["']config_url["']\s*:\s*["']([^"']+)["']/i)?.[1]
    if (configValue) {
      const config = await fetchVimeoControlJson<VimeoConfig>(decodeHtml(configValue), {
        ...JSON_HEADERS,
        Referer: embedUrl,
        Origin: 'https://player.vimeo.com',
      }, 'Vimeo player config request')
      return { config, embedUrl }
    }
  }

  const configUrl = new URL(embedUrl)
  configUrl.pathname = `${configUrl.pathname.replace(/\/$/, '')}/config`
  const config = await fetchVimeoControlJson<VimeoConfig>(configUrl.toString(), {
    ...JSON_HEADERS,
    Referer: embedUrl,
    Origin: 'https://player.vimeo.com',
  }, 'Vimeo canonical config request')
  return { config, embedUrl }
}

function progressive(config: VimeoConfig): VimeoProgressive[] {
  return (config.video?.files?.progressive || config.request?.files?.progressive || [])
    .filter((item) => typeof item.url === 'string' && item.url.length > 0)
    .sort((a, b) => (b.height || 0) - (a.height || 0))
}

function pickProgressive(config: VimeoConfig, quality: string): VimeoProgressive | null {
  const formats = progressive(config)
  if (!formats.length) return null
  if (quality === 'best') return formats[0]
  const height = Number.parseInt(quality, 10)
  if (Number.isFinite(height)) {
    return formats.find((item) => item.height === height)
      || formats.find((item) => (item.height || 0) <= height)
      || formats[formats.length - 1]
  }
  return formats.find((item) => item.quality === quality) || formats[0]
}

function hlsUrl(config: VimeoConfig): string | null {
  const hls = config.request?.files?.hls || config.video?.files?.hls
  if (!hls?.cdns) return null
  const preferred = hls.default_cdn ? hls.cdns[hls.default_cdn]?.url : undefined
  if (preferred) return preferred
  return Object.values(hls.cdns).find((item) => typeof item?.url === 'string' && item.url.length > 0)?.url || null
}

function allowedTarget(raw: string): URL | null {
  try {
    const url = new URL(raw)
    if (url.protocol !== 'https:') return null
    const hostname = url.hostname.toLowerCase()
    const allowed = ALLOWED_MEDIA_SUFFIXES.some((suffix) => hostname === suffix || hostname.endsWith(`.${suffix}`))
    return allowed ? url : null
  } catch {
    return null
  }
}

function relayUrl(request: NextRequest, id: string, target: URL): string {
  const url = new URL('/api/vimeo-media', request.nextUrl.origin)
  url.searchParams.set('id', id)
  url.searchParams.set('mode', 'hls-resource')
  url.searchParams.set('target', target.toString())
  return `${url.pathname}?${url.searchParams.toString()}`
}

function rewriteUri(base: URL, raw: string, request: NextRequest, id: string): string {
  try {
    const target = new URL(raw, base)
    if (!allowedTarget(target.toString())) return raw
    return relayUrl(request, id, target)
  } catch {
    return raw
  }
}

function rewritePlaylist(text: string, base: URL, request: NextRequest, id: string): string {
  return text
    .split(/\r?\n/)
    .map((line) => {
      const trimmed = line.trim()
      if (!trimmed) return line
      if (!trimmed.startsWith('#')) return rewriteUri(base, trimmed, request, id)
      return line.replace(/URI="([^"]+)"/g, (_match, uri: string) => `URI="${rewriteUri(base, uri, request, id)}"`)
    })
    .join('\n')
}

function isPlaylist(url: URL, response: Response): boolean {
  const contentType = response.headers.get('content-type')?.toLowerCase() || ''
  return url.pathname.toLowerCase().endsWith('.m3u8')
    || contentType.includes('mpegurl')
    || contentType.includes('vnd.apple.mpegurl')
}

function copyHeader(from: Headers, to: Headers, name: string) {
  const value = from.get(name)
  if (value) to.set(name, value)
}

async function proxyTarget(request: NextRequest, id: string, target: URL, embedUrl: string, headOnly: boolean) {
  const headers = new Headers({
    Accept: '*/*',
    'Accept-Language': 'en-US,en;q=0.9',
    'User-Agent': USER_AGENT,
    Referer: embedUrl,
    Origin: 'https://player.vimeo.com',
  })
  const range = request.headers.get('range')
  if (range) headers.set('Range', range)

  let upstream: Response
  try {
    // Do not use the short control-plane timeout for media bodies. Large media
    // and HLS resources must remain streamable for as long as the client needs.
    upstream = await fetch(target.toString(), {
      method: 'GET',
      headers,
      redirect: 'follow',
      cache: 'no-store',
    })
  } catch {
    return failure('Unable to fetch Vimeo media resource', 502)
  }

  if (!upstream.ok || (!upstream.body && !headOnly)) {
    void upstream.body?.cancel()
    return failure(`Vimeo media resource returned ${upstream.status}`, 502)
  }

  const responseHeaders = new Headers()
  responseHeaders.set('Cache-Control', 'private, no-store')
  responseHeaders.set('Cross-Origin-Resource-Policy', 'same-origin')
  responseHeaders.set('X-Robots-Tag', 'noindex, nofollow, noarchive')
  copyHeader(upstream.headers, responseHeaders, 'accept-ranges')
  copyHeader(upstream.headers, responseHeaders, 'content-length')
  copyHeader(upstream.headers, responseHeaders, 'content-range')
  copyHeader(upstream.headers, responseHeaders, 'etag')
  copyHeader(upstream.headers, responseHeaders, 'last-modified')

  if (isPlaylist(target, upstream)) {
    if (headOnly) {
      void upstream.body?.cancel()
      responseHeaders.set('Content-Type', 'application/vnd.apple.mpegurl; charset=utf-8')
      return new NextResponse(null, { status: upstream.status, headers: responseHeaders })
    }
    const text = await upstream.text()
    responseHeaders.set('Content-Type', 'application/vnd.apple.mpegurl; charset=utf-8')
    responseHeaders.delete('content-length')
    return new NextResponse(rewritePlaylist(text, target, request, id), { status: upstream.status, headers: responseHeaders })
  }

  copyHeader(upstream.headers, responseHeaders, 'content-type')
  return new NextResponse(headOnly ? null : upstream.body, { status: upstream.status, headers: responseHeaders })
}

async function resolveInitial(request: NextRequest, id: string): Promise<{ media: ResolvedMedia; embedUrl: string }> {
  const { config, embedUrl } = await fetchConfig(id)
  const mode = request.nextUrl.searchParams.get('mode')?.trim() || 'progressive'
  if (mode === 'hls') {
    const hls = hlsUrl(config)
    if (!hls) throw new Error('Vimeo HLS stream not available')
    return { media: { url: hls, referer: embedUrl, filename: `vimeo-${id}.m3u8` }, embedUrl }
  }

  const quality = request.nextUrl.searchParams.get('quality')?.trim() || 'best'
  const selected = pickProgressive(config, quality)
  if (!selected?.url) throw new Error('Vimeo progressive stream not available')
  return { media: { url: selected.url, referer: embedUrl, filename: `vimeo-${id}.mp4` }, embedUrl }
}

async function handle(request: NextRequest, headOnly: boolean) {
  const id = request.nextUrl.searchParams.get('id')?.trim() || ''
  if (!/^\d{5,}$/.test(id)) return failure('Invalid Vimeo id', 400)

  const mode = request.nextUrl.searchParams.get('mode')?.trim() || 'progressive'
  if (mode === 'hls-resource') {
    const rawTarget = request.nextUrl.searchParams.get('target')?.trim() || ''
    const target = allowedTarget(rawTarget)
    if (!target) return failure('Vimeo relay target is not allowed', 403)
    const embedUrl = `https://player.vimeo.com/video/${id}`
    return proxyTarget(request, id, target, embedUrl, headOnly)
  }

  try {
    const { media, embedUrl } = await resolveInitial(request, id)
    const target = allowedTarget(media.url)
    if (!target) return failure('Resolved Vimeo media target is not allowed', 403)
    const response = await proxyTarget(request, id, target, embedUrl, headOnly)
    if (!headOnly && mode !== 'hls' && response.ok) {
      response.headers.set('Content-Disposition', `attachment; filename="${media.filename}"`)
    }
    return response
  } catch (error) {
    return failure(error instanceof Error ? error.message : 'Unable to resolve Vimeo media', 502)
  }
}

export async function GET(request: NextRequest) {
  return handle(request, false)
}

export async function HEAD(request: NextRequest) {
  return handle(request, true)
}
