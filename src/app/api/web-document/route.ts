import { NextRequest, NextResponse } from 'next/server'

import type { UnifiedParseResult } from '@/lib/types'
import { extractWebDocumentFromHtml } from '@/lib/web-document'

const USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36'
const MAX_HTML_BYTES = 8 * 1024 * 1024
const MAX_REDIRECTS = 5

const VIDEO_FIRST_HOSTS = [
    'youtube.com', 'youtu.be', 'vimeo.com', 'dailymotion.com', 'dai.ly',
    'bilibili.com', 'tiktok.com', 'instagram.com', 'twitter.com', 'x.com',
    'twitch.tv', 'soundcloud.com', 'reddit.com', 'pinterest.com', 'streamable.com',
    'nicovideo.jp', 'niconico.com', 'vk.com', 'tumblr.com', 'threads.net',
]

function noStoreJson(payload: UnifiedParseResult, status = 200) {
    const response = NextResponse.json(payload, { status })
    response.headers.set('Cache-Control', 'no-store')
    response.headers.set('X-Robots-Tag', 'noindex, nofollow, noarchive')
    return response
}

function isPrivateIpv4(hostname: string): boolean {
    const match = hostname.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/)
    if (!match) return false
    const octets = match.slice(1).map(Number)
    if (octets.some((value) => value < 0 || value > 255)) return true
    const [a, b] = octets
    return a === 0
        || a === 10
        || a === 127
        || (a === 169 && b === 254)
        || (a === 172 && b >= 16 && b <= 31)
        || (a === 192 && b === 168)
        || (a === 100 && b >= 64 && b <= 127)
        || a >= 224
}

function isSafePublicUrl(url: URL): boolean {
    if (!['http:', 'https:'].includes(url.protocol)) return false
    const hostname = url.hostname.toLowerCase().replace(/^\[|\]$/g, '')
    if (!hostname || hostname === 'localhost' || hostname.endsWith('.localhost') || hostname.endsWith('.local')) return false
    if (isPrivateIpv4(hostname)) return false
    if (hostname === '::1' || hostname.startsWith('fc') || hostname.startsWith('fd') || hostname.startsWith('fe80:')) return false
    return true
}

function hostMatches(hostname: string, domain: string): boolean {
    return hostname === domain || hostname.endsWith(`.${domain}`)
}

function isVideoFirstHost(url: URL): boolean {
    const host = url.hostname.toLowerCase()

    // Xiaohongshu already has a dedicated resolver that reliably distinguishes
    // video works from image notes and also returns the post caption. Let that
    // resolver remain authoritative instead of mistaking a video thumbnail for
    // a one-image note.
    if (hostMatches(host, 'xiaohongshu.com') || host === 'xhslink.com') return true

    // Douyin's /note/ URLs are explicitly image/text works. Normal /video/
    // pages continue to yt-dlp/shared media parsing so a cover image can never
    // hide the actual video result.
    if (hostMatches(host, 'douyin.com')) {
        return !/(?:^|\/)note(?:\/|$)/i.test(url.pathname)
    }

    return VIDEO_FIRST_HOSTS.some((domain) => hostMatches(host, domain))
}

async function fetchHtml(startUrl: URL): Promise<{ html: string; finalUrl: URL }> {
    let current = startUrl
    for (let redirectCount = 0; redirectCount <= MAX_REDIRECTS; redirectCount += 1) {
        if (!isSafePublicUrl(current)) throw new Error('URL is not allowed')
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

export async function GET(request: NextRequest) {
    const sourceUrl = request.nextUrl.searchParams.get('url')?.trim() || ''
    let parsed: URL
    try {
        parsed = new URL(sourceUrl)
    } catch {
        return noStoreJson({ success: false, code: 'BAD_REQUEST', status: 400, error: 'Invalid source URL', url: sourceUrl }, 400)
    }
    if (!isSafePublicUrl(parsed)) {
        return noStoreJson({ success: false, code: 'BAD_REQUEST', status: 400, error: 'URL is not allowed', url: sourceUrl }, 400)
    }
    if (isVideoFirstHost(parsed)) {
        return noStoreJson({ success: false, code: 'UNSUPPORTED_PLATFORM', status: 422, error: 'Prefer the media parser for this platform', url: sourceUrl }, 422)
    }

    try {
        const { html, finalUrl } = await fetchHtml(parsed)
        const document = extractWebDocumentFromHtml(finalUrl.toString(), html)
        if (!document) {
            return noStoreJson({ success: false, code: 'UNSUPPORTED_PLATFORM', status: 422, error: 'No downloadable document media found', url: sourceUrl }, 422)
        }

        const images = document.images
        const videos = document.videos
        const cover = images[0]?.downloadUrl || images[0]?.url || null
        return noStoreJson({
            success: true,
            data: {
                title: document.title,
                desc: document.description || document.textContent.slice(0, 1200),
                textContent: document.textContent,
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