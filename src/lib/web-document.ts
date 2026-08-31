import type { EmbeddedVideoInfo, UnifiedParseResultImage } from '@/lib/types'

export type WebDocumentType = 'post' | 'article' | 'product' | 'gallery' | 'webpage'

export interface ParsedWebDocument {
    title: string
    description: string
    textContent: string
    author?: string
    publishedAt?: string
    siteName?: string
    platform: string
    documentType: WebDocumentType
    images: UnifiedParseResultImage[]
    videos: EmbeddedVideoInfo[]
}

const MAX_IMAGES = 120
const MAX_VIDEOS = 30
const MAX_JSON_NODES = 20_000

const IMAGE_KEY_RE = /(?:^|_)(?:image|images|imageurl|image_url|img|pic|picture|photo|photos|poster|thumbnail|cover|src)(?:$|_)/i
const VIDEO_KEY_RE = /(?:^|_)(?:video|videos|videourl|video_url|contenturl|content_url|playurl|play_url|playaddr|play_addr|streamurl|stream_url|src|url)(?:$|_)/i
const TEXT_KEY_RE = /^(?:description|desc|caption|content|content_text|text|summary)$/i
const TITLE_KEY_RE = /^(?:name|title|headline)$/i
const AUTHOR_KEY_RE = /^(?:author|authorname|author_name|nickname|user_name|username)$/i
const DATE_KEY_RE = /^(?:datepublished|date_published|publishdate|publish_date|publishedat|published_at|uploadDate)$/i
const IMAGE_EXT_RE = /\.(?:avif|bmp|gif|jpe?g|png|webp)(?:$|[?#])/i
const VIDEO_EXT_RE = /\.(?:m4v|mov|mp4|webm)(?:$|[?#])/i
const TRACKING_ASSET_RE = /(?:sprite|favicon|icon[-_/]|logo[-_/]|avatar[-_/]|badge|placeholder|loading|spacer|pixel)[^/]*\.(?:gif|jpe?g|png|webp)/i
const EXTENSIONLESS_IMAGE_HOST_RE = /(?:^|\.)(?:mmbiz\.qpic\.cn|qpic\.cn|douyinpic\.com|xhscdn\.com|alicdn\.com|shopifycdn\.net)$/i

function decodeHtml(value: string): string {
    return value
        .replace(/&amp;/gi, '&')
        .replace(/&quot;/gi, '"')
        .replace(/&#39;|&apos;/gi, "'")
        .replace(/&lt;/gi, '<')
        .replace(/&gt;/gi, '>')
        .replace(/&nbsp;/gi, ' ')
        .replace(/&#(\d+);/g, (_, raw: string) => String.fromCodePoint(Number(raw) || 32))
        .replace(/&#x([0-9a-f]+);/gi, (_, raw: string) => String.fromCodePoint(Number.parseInt(raw, 16) || 32))
        .replace(/\\u0026/gi, '&')
        .replace(/\\u003d/gi, '=')
        .replace(/\\u002f/gi, '/')
        .replace(/\\\//g, '/')
}

function cleanText(value: string): string {
    return decodeHtml(value)
        .replace(/<br\s*\/?\s*>/gi, '\n')
        .replace(/<\/(?:p|div|section|article|li|h[1-6]|blockquote)>/gi, '\n')
        .replace(/<[^>]+>/g, ' ')
        .replace(/[\t\f\v ]+/g, ' ')
        .replace(/\s*\n\s*/g, '\n')
        .replace(/\n{3,}/g, '\n\n')
        .trim()
}

function attrMap(tag: string): Record<string, string> {
    const result: Record<string, string> = {}
    const re = /([:\w-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/g
    for (const match of tag.matchAll(re)) {
        result[match[1]!.toLowerCase()] = decodeHtml(match[2] ?? match[3] ?? match[4] ?? '')
    }
    return result
}

function absoluteHttpUrl(raw: string | undefined, base: URL): string | null {
    if (!raw) return null
    let value = decodeHtml(raw).trim()
    if (!value || /^(?:data|blob|javascript):/i.test(value)) return null
    if (value.includes(',')) value = value.split(',')[0]!.trim().split(/\s+/)[0]!
    try {
        const url = new URL(value, base)
        if (!/^https?:$/.test(url.protocol)) return null
        url.hash = ''
        return url.toString()
    } catch {
        return null
    }
}

function metaValues(html: string, key: string): string[] {
    const result: string[] = []
    for (const match of html.matchAll(/<meta\b[^>]*>/gi)) {
        const attrs = attrMap(match[0])
        const identity = (attrs.property || attrs.name || attrs.itemprop || '').toLowerCase()
        if (identity === key.toLowerCase() && attrs.content) result.push(attrs.content)
    }
    return result
}

function firstMeta(html: string, keys: string[]): string {
    for (const key of keys) {
        const value = metaValues(html, key)[0]
        if (value?.trim()) return cleanText(value)
    }
    return ''
}

function pageTitle(html: string): string {
    const meta = firstMeta(html, ['og:title', 'twitter:title'])
    if (meta) return meta
    return cleanText(html.match(/<title\b[^>]*>([\s\S]*?)<\/title>/i)?.[1] || '')
}

function uniquePush(list: string[], seen: Set<string>, value: string | null, limit: number) {
    if (!value || list.length >= limit || seen.has(value)) return
    seen.add(value)
    list.push(value)
}

function looksLikeImage(url: string, key = ''): boolean {
    if (TRACKING_ASSET_RE.test(url)) return false
    if (IMAGE_EXT_RE.test(url)) return true
    try {
        if (EXTENSIONLESS_IMAGE_HOST_RE.test(new URL(url).hostname.toLowerCase())) return true
    } catch {
        // absoluteHttpUrl validates URLs before this helper is called.
    }
    return /(?:src|image|img|photo|pic|cover|poster|thumbnail)/i.test(key)
        && /(?:image|img|photo|pic|qpic|alicdn|cloudfront|cdn|media)/i.test(url)
}

function looksLikeVideo(url: string, key = ''): boolean {
    if (VIDEO_EXT_RE.test(url)) return true
    return VIDEO_KEY_RE.test(key) && /(?:video|vod|media|stream|play)/i.test(url) && !/\.(?:jpe?g|png|webp|gif)(?:$|[?#])/i.test(url)
}

function parseJsonCandidate(raw: string): unknown | null {
    const candidates = [raw.trim()]
    if (/%(?:7b|5b)/i.test(raw)) {
        try {
            candidates.push(decodeURIComponent(raw.trim()))
        } catch {
            // Ignore malformed percent-encoding.
        }
    }
    for (const candidate of candidates) {
        const normalized = candidate.replace(/^<!--|-->$/g, '').trim()
        if (!normalized || !/^[\[{]/.test(normalized)) continue
        try {
            return JSON.parse(normalized)
        } catch {
            // Some hydration payloads wrap JSON in one quoted string.
            try {
                const parsed = JSON.parse(`"${normalized.replace(/"/g, '\\"')}"`)
                if (typeof parsed === 'string') return JSON.parse(parsed)
            } catch {
                // Keep trying other script blocks.
            }
        }
    }
    return null
}

function scriptJsonValues(html: string): unknown[] {
    const result: unknown[] = []
    for (const match of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)) {
        const attrs = attrMap(match[1] || '')
        const body = (match[2] || '').trim()
        if (!body || body.length > 2_500_000) continue
        const likelyJson = /json/i.test(attrs.type || '')
            || /(?:__next_data__|serialized-server-data|render_data|__initial_state__|__data__|product)/i.test(attrs.id || '')
            || /^[\[{]/.test(body)
            || /^%7b|^%5b/i.test(body)
        if (!likelyJson) continue
        const value = parseJsonCandidate(body)
        if (value !== null) result.push(value)
    }
    return result
}

function collectJsonData(
    value: unknown,
    base: URL,
    images: string[],
    imageSeen: Set<string>,
    videos: string[],
    videoSeen: Set<string>,
): { title: string; description: string; author: string; publishedAt: string } {
    let title = ''
    let description = ''
    let author = ''
    let publishedAt = ''
    const stack: Array<{ value: unknown; key: string }> = [{ value, key: '' }]
    let visited = 0

    while (stack.length && visited < MAX_JSON_NODES) {
        const current = stack.pop()!
        visited += 1
        if (typeof current.value === 'string') {
            const raw = current.value.trim()
            if (!raw) continue
            if (!title && TITLE_KEY_RE.test(current.key) && raw.length < 300) title = cleanText(raw)
            if (!description && TEXT_KEY_RE.test(current.key) && raw.length < 20_000) description = cleanText(raw)
            if (!author && AUTHOR_KEY_RE.test(current.key) && raw.length < 200) author = cleanText(raw)
            if (!publishedAt && DATE_KEY_RE.test(current.key) && raw.length < 100) publishedAt = cleanText(raw)
            const url = absoluteHttpUrl(raw, base)
            if (url && looksLikeImage(url, current.key)) uniquePush(images, imageSeen, url, MAX_IMAGES)
            if (url && looksLikeVideo(url, current.key)) uniquePush(videos, videoSeen, url, MAX_VIDEOS)
            continue
        }
        if (!current.value || typeof current.value !== 'object') continue
        if (Array.isArray(current.value)) {
            for (let index = current.value.length - 1; index >= 0; index -= 1) {
                stack.push({ value: current.value[index], key: current.key })
            }
            continue
        }
        for (const [key, child] of Object.entries(current.value as Record<string, unknown>)) {
            stack.push({ value: child, key })
        }
    }
    return { title, description, author, publishedAt }
}

function extractElementMedia(html: string, base: URL, images: string[], imageSeen: Set<string>, videos: string[], videoSeen: Set<string>) {
    for (const match of html.matchAll(/<(?:img|source)\b[^>]*>/gi)) {
        const attrs = attrMap(match[0])
        for (const key of ['data-src', 'data-original', 'data-lazy-src', 'data-actualsrc', 'src', 'srcset']) {
            const url = absoluteHttpUrl(attrs[key], base)
            if (url && looksLikeImage(url, key)) uniquePush(images, imageSeen, url, MAX_IMAGES)
        }
    }
    for (const match of html.matchAll(/<(?:video|source|a)\b[^>]*>/gi)) {
        const attrs = attrMap(match[0])
        for (const key of ['src', 'data-src', 'href']) {
            const url = absoluteHttpUrl(attrs[key], base)
            if (url && looksLikeVideo(url, key)) uniquePush(videos, videoSeen, url, MAX_VIDEOS)
        }
    }
}

function wechatArticleText(html: string): string {
    const marker = html.search(/\bid=["']js_content["']/i)
    if (marker < 0) return ''
    const start = html.lastIndexOf('<', marker)
    if (start < 0) return ''
    const tail = html.slice(start)
    const endCandidates = [
        tail.search(/<script\b/i),
        tail.search(/\bid=["']js_toobar3["']/i),
        tail.search(/\bclass=["'][^"']*rich_media_tool/i),
    ].filter((value) => value > 0)
    const end = endCandidates.length ? Math.min(...endCandidates) : Math.min(tail.length, 2_000_000)
    return cleanText(tail.slice(0, end))
}

function classifyPlatform(base: URL, html: string): { platform: string; documentType: WebDocumentType } {
    const host = base.hostname.toLowerCase()
    if (/(^|\.)xiaohongshu\.com$/.test(host) || host === 'xhslink.com') return { platform: 'xiaohongshu', documentType: 'post' }
    if (/(^|\.)douyin\.com$/.test(host)) return { platform: 'douyin', documentType: 'post' }
    if (/(^|\.)mp\.weixin\.qq\.com$/.test(host) || /(^|\.)weixin\.qq\.com$/.test(host)) return { platform: 'wechat', documentType: 'article' }
    if (/(^|\.)amazon\./.test(host) || host.includes('.amazon.')) return { platform: 'generic', documentType: 'product' }
    if (/(^|\.)ebay\./.test(host) || host.includes('.ebay.')) return { platform: 'generic', documentType: 'product' }
    if (/(^|\.)aliexpress\./.test(host) || host.includes('.aliexpress.')) return { platform: 'generic', documentType: 'product' }
    if (/(^|\.)alibaba\.com$/.test(host)) return { platform: 'generic', documentType: 'product' }
    if (/shopify/i.test(html) || /cdn\.shopify\.com/i.test(html)) return { platform: 'generic', documentType: 'product' }
    if (/<article\b/i.test(html)) return { platform: 'generic', documentType: 'article' }
    return { platform: 'generic', documentType: 'webpage' }
}

export function extractWebDocumentFromHtml(sourceUrl: string, html: string): ParsedWebDocument | null {
    let base: URL
    try {
        base = new URL(sourceUrl)
    } catch {
        return null
    }

    const images: string[] = []
    const videos: string[] = []
    const imageSeen = new Set<string>()
    const videoSeen = new Set<string>()

    for (const key of ['og:image', 'twitter:image', 'twitter:image:src']) {
        for (const raw of metaValues(html, key)) uniquePush(images, imageSeen, absoluteHttpUrl(raw, base), MAX_IMAGES)
    }
    for (const key of ['og:video', 'og:video:url', 'og:video:secure_url', 'twitter:player:stream']) {
        for (const raw of metaValues(html, key)) {
            const url = absoluteHttpUrl(raw, base)
            if (url && looksLikeVideo(url, key)) uniquePush(videos, videoSeen, url, MAX_VIDEOS)
        }
    }

    let jsonTitle = ''
    let jsonDescription = ''
    let jsonAuthor = ''
    let jsonPublishedAt = ''
    for (const payload of scriptJsonValues(html)) {
        const found = collectJsonData(payload, base, images, imageSeen, videos, videoSeen)
        jsonTitle ||= found.title
        jsonDescription ||= found.description
        jsonAuthor ||= found.author
        jsonPublishedAt ||= found.publishedAt
    }

    extractElementMedia(html, base, images, imageSeen, videos, videoSeen)

    const classification = classifyPlatform(base, html)
    const title = pageTitle(html) || jsonTitle || base.hostname
    const metaDescription = firstMeta(html, ['og:description', 'twitter:description', 'description'])
    const description = metaDescription || jsonDescription
    const author = firstMeta(html, ['author', 'article:author']) || jsonAuthor || undefined
    const publishedAt = firstMeta(html, ['article:published_time', 'date', 'pubdate']) || jsonPublishedAt || undefined
    const siteName = firstMeta(html, ['og:site_name', 'application-name']) || undefined
    const articleText = classification.platform === 'wechat' ? wechatArticleText(html) : ''
    const textContent = articleText || description

    const usefulImages = images.filter((url, index) => index === 0 || !TRACKING_ASSET_RE.test(url)).slice(0, MAX_IMAGES)
    const usefulVideos = videos.filter((url) => VIDEO_EXT_RE.test(url) || /(?:video|vod|media)/i.test(url)).slice(0, MAX_VIDEOS)

    // Do not hijack ordinary video pages that yt-dlp/shared parsers handle better.
    const hasDocumentSignal = classification.documentType !== 'webpage'
        || usefulImages.length >= 2
        || (usefulImages.length >= 1 && textContent.length >= 20)
        || usefulVideos.length >= 1
    if (!hasDocumentSignal) return null

    return {
        title,
        description,
        textContent,
        author,
        publishedAt,
        siteName,
        platform: classification.platform,
        documentType: classification.documentType,
        images: usefulImages.map((url, index) => ({ index: index + 1, url, downloadUrl: url })),
        videos: usefulVideos.map((url, index) => ({
            id: `document-video-${index + 1}`,
            title: `${title} · ${index + 1}`,
            downloadVideoUrl: url,
            originDownloadVideoUrl: url,
            downloadAudioUrl: null,
            originDownloadAudioUrl: null,
            videoAudioMode: 'muxed',
            mediaActions: { video: 'direct-download', audio: 'extract-audio' },
        })),
    }
}
