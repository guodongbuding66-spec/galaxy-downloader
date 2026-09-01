import { NextRequest, NextResponse } from 'next/server'

import { extractDocumentMarkdown } from '@/lib/document-markdown'
import { isSafePublicHttpUrl } from '@/lib/public-url'
import type { EmbeddedVideoInfo, UnifiedParseResult } from '@/lib/types'
import { extractWebDocumentFromHtml, type ParsedWebDocument } from '@/lib/web-document'

const USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36'
const MAX_HTML_BYTES = 8 * 1024 * 1024
const MAX_REDIRECTS = 5

const VIDEO_FIRST_HOSTS = [
    'youtube.com', 'youtu.be', 'vimeo.com', 'dailymotion.com', 'dai.ly',
    'bilibili.com', 'tiktok.com', 'instagram.com', 'twitter.com', 'x.com',
    'twitch.tv', 'soundcloud.com', 'reddit.com', 'pinterest.com', 'streamable.com',
    'nicovideo.jp', 'niconico.com', 'vk.com', 'tumblr.com', 'threads.net',
]

const CHALLENGE_RE = /(?:wappoc_appmsgcaptcha|captcha\.gtimg\.com|verify you are human|are you a human|robot check|security check|unusual traffic|automated access|enter the characters you see below|press and hold|cf-chl-|challenge-platform)/i

function noStoreJson(payload: UnifiedParseResult, status = 200) {
    const response = NextResponse.json(payload, { status })
    response.headers.set('Cache-Control', 'no-store')
    response.headers.set('X-Robots-Tag', 'noindex, nofollow, noarchive')
    return response
}

function hostMatches(hostname: string, domain: string): boolean {
    return hostname === domain || hostname.endsWith(`.${domain}`)
}

function isVideoFirstHost(url: URL): boolean {
    const host = url.hostname.toLowerCase()
    const path = url.pathname

    if (hostMatches(host, 'xiaohongshu.com') || host === 'xhslink.com') return true
    if (hostMatches(host, 'douyin.com')) return !/(?:^|\/)note(?:\/|$)/i.test(path)
    if (hostMatches(host, 'tiktok.com')) return !/(?:^|\/)photo(?:\/|$)/i.test(path)
    if (hostMatches(host, 'instagram.com')) {
        if (/(?:^|\/)(?:reel|reels|tv)(?:\/|$)/i.test(path)) return true
        return !/(?:^|\/)p(?:\/|$)/i.test(path)
    }
    if (hostMatches(host, 'reddit.com') || hostMatches(host, 'redd.it')) {
        return !/(?:^|\/)(?:gallery|comments)(?:\/|$)/i.test(path)
    }
    if (hostMatches(host, 'pinterest.com') || host === 'pin.it') return false
    if (hostMatches(host, 'twitter.com') || hostMatches(host, 'x.com')) {
        return !/(?:^|\/)status(?:\/|$)/i.test(path)
    }
    if (hostMatches(host, 'threads.net')) return !/(?:^|\/)post(?:\/|$)/i.test(path)
    if (hostMatches(host, 'tumblr.com')) return false

    return VIDEO_FIRST_HOSTS.some((domain) => hostMatches(host, domain))
}

async function fetchHtml(startUrl: URL): Promise<{ html: string; finalUrl: URL }> {
    let current = startUrl
    for (let redirectCount = 0; redirectCount <= MAX_REDIRECTS; redirectCount += 1) {
        if (!isSafePublicHttpUrl(current)) throw new Error('URL is not allowed')
        const response = await fetch(current, {
            method: 'GET',
            redirect: 'manual',
            cache: 'no-store',
            headers: {
                Accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.5',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.7',
                'Accept-Encoding': 'identity',
                'User-Agent': USER_AGENT,
            },
        })
        if (response.status >= 300 && response.status < 400) {
            const location = response.headers.get('location')
            if (!location) throw new Error(`Redirect ${response.status} without Location`)
            void response.body?.cancel()
            current = new URL(location, current)
            continue
        }
        if (!response.ok) throw new Error(`Page request failed (${response.status})`)
        const contentType = response.headers.get('content-type') || ''
        if (contentType && !/(?:text\/html|application\/xhtml\+xml|text\/plain)/i.test(contentType)) {
            throw new Error(`Unsupported document content type: ${contentType}`)
        }
        const declaredLength = Number(response.headers.get('content-length') || 0)
        if (declaredLength > MAX_HTML_BYTES) throw new Error('Document is too large to parse safely')
        const buffer = await response.arrayBuffer()
        if (buffer.byteLength > MAX_HTML_BYTES) throw new Error('Document is too large to parse safely')
        return { html: new TextDecoder().decode(buffer), finalUrl: current }
    }
    throw new Error('Too many redirects')
}

function hasMeaningfulDocumentSignal(document: ParsedWebDocument, markdownContent: string): boolean {
    const text = (document.textContent || document.description || '').trim()
    const images = document.images.length
    const videos = document.videos.length
    if (document.documentType === 'product') return images >= 1 || videos >= 1 || text.length >= 20
    if (document.documentType === 'article') return Boolean(markdownContent) || text.length >= 20 || images >= 2 || videos >= 1
    if (document.documentType === 'post' || document.documentType === 'gallery') return images >= 1 || videos >= 1 || text.length >= 20
    return images >= 2 || videos >= 1 || (images >= 1 && text.length >= 20)
}

function proxiedEmbeddedVideos(
    request: NextRequest,
    sourceUrl: string,
    videos: EmbeddedVideoInfo[],
): EmbeddedVideoInfo[] {
    return videos.map((video, index) => {
        const raw = video.originDownloadVideoUrl || video.downloadVideoUrl || ''
        if (!raw) return video
        const proxy = new URL('/api/proxy-media', request.nextUrl.origin)
        proxy.searchParams.set('url', raw)
        proxy.searchParams.set('source', sourceUrl)
        proxy.searchParams.set('name', `${video.title || 'media'}-${index + 1}`)
        return {
            ...video,
            downloadVideoUrl: proxy.toString(),
            originDownloadVideoUrl: raw,
        }
    })
}

export async function GET(request: NextRequest) {
    const sourceUrl = request.nextUrl.searchParams.get('url')?.trim() || ''
    let parsed: URL
    try {
        parsed = new URL(sourceUrl)
    } catch {
        return noStoreJson({ success: false, code: 'BAD_REQUEST', status: 400, error: 'Invalid source URL', url: sourceUrl }, 400)
    }
    if (!isSafePublicHttpUrl(parsed)) {
        return noStoreJson({ success: false, code: 'BAD_REQUEST', status: 400, error: 'URL is not allowed', url: sourceUrl }, 400)
    }
    if (isVideoFirstHost(parsed)) {
        return noStoreJson({ success: false, code: 'UNSUPPORTED_PLATFORM', status: 422, error: 'Prefer the media parser for this platform', url: sourceUrl }, 422)
    }

    try {
        const { html, finalUrl } = await fetchHtml(parsed)
        if (CHALLENGE_RE.test(`${finalUrl.toString()}\n${html.slice(0, 1_500_000)}`)) {
            return noStoreJson({
                success: false,
                code: 'AUTH_REQUIRED',
                status: 401,
                error: 'The target page returned a CAPTCHA or automated-access challenge.',
                details: { parser: 'web-document', documentChallenge: true },
                url: sourceUrl,
            }, 401)
        }

        const document = extractWebDocumentFromHtml(finalUrl.toString(), html)
        if (!document) {
            return noStoreJson({ success: false, code: 'UNSUPPORTED_PLATFORM', status: 422, error: 'No downloadable document media found', url: sourceUrl }, 422)
        }
        const markdownContent = extractDocumentMarkdown(finalUrl.toString(), html, document.platform)
        if (!hasMeaningfulDocumentSignal(document, markdownContent)) {
            return noStoreJson({
                success: false,
                code: 'UNSUPPORTED_PLATFORM',
                status: 422,
                error: 'The static page is only a shell; try local dynamic rendering.',
                details: { parser: 'web-document', staticShell: true },
                url: sourceUrl,
            }, 422)
        }

        const images = document.images
        const videos = proxiedEmbeddedVideos(request, sourceUrl, document.videos)
        const cover = images[0]?.downloadUrl || images[0]?.url || null
        return noStoreJson({
            success: true,
            data: {
                title: document.title,
                desc: document.description || document.textContent.slice(0, 1200),
                textContent: document.textContent,
                markdownContent: markdownContent || undefined,
                author: document.author,
                publishedAt: document.publishedAt,
                siteName: document.siteName,
                documentType: document.documentType,
                cover,
                platform: document.platform,
                downloadAudioUrl: null,
                downloadVideoUrl: null,
                originDownloadAudioUrl: null,
                originDownloadVideoUrl: null,
                videoAudioMode: 'not_applicable',
                mediaActions: { video: 'hide', audio: 'hide' },
                url: sourceUrl,
                kind: 'image',
                noteType: 'image',
                images,
                videos,
            },
        })
    } catch (error) {
        const message = error instanceof Error ? error.message : String(error)
        return noStoreJson({
            success: false,
            code: 'UPSTREAM_ERROR',
            status: 502,
            error: message,
            details: { parser: 'web-document' },
            url: sourceUrl,
        }, 502)
    }
}
