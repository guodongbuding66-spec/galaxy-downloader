import { NextRequest, NextResponse } from 'next/server'

const USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36'
const MAX_REDIRECTS = 5
const MAX_DECLARED_BYTES = 8 * 1024 * 1024 * 1024

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
    const host = url.hostname.toLowerCase().replace(/^\[|\]$/g, '')
    if (!host || host === 'localhost' || host.endsWith('.localhost') || host.endsWith('.local')) return false
    if (isPrivateIpv4(host)) return false
    if (host === '::1' || host.startsWith('fc') || host.startsWith('fd') || host.startsWith('fe80:')) return false
    return true
}

function safeSourceReferer(value: string | null): string | null {
    if (!value) return null
    try {
        const url = new URL(value)
        if (!isSafePublicUrl(url)) return null
        return url.toString()
    } catch {
        return null
    }
}

function extensionFromUrl(url: URL): string {
    const extension = url.pathname.match(/\.([a-z0-9]{2,6})$/i)?.[1]?.toLowerCase()
    return extension && /^(?:m4v|mov|mp4|webm)$/.test(extension) ? extension : 'mp4'
}

function safeFilename(value: string, fallback: string): string {
    const cleaned = value
        .replace(/[\u0000-\u001f\u007f<>:"/\\|?*]+/g, '-')
        .replace(/\s+/g, ' ')
        .trim()
        .slice(0, 120)
    return cleaned || fallback
}

async function fetchMedia(
    initialUrl: URL,
    sourceReferer: string | null,
    range: string | null,
): Promise<{ response: Response; finalUrl: URL }> {
    let current = initialUrl
    for (let redirect = 0; redirect <= MAX_REDIRECTS; redirect += 1) {
        if (!isSafePublicUrl(current)) throw new Error('Media URL is not allowed')
        const headers = new Headers({
            Accept: 'video/mp4,video/webm,video/*;q=0.9,application/octet-stream;q=0.8,*/*;q=0.5',
            'Accept-Encoding': 'identity',
            'User-Agent': USER_AGENT,
        })
        if (sourceReferer) headers.set('Referer', sourceReferer)
        if (range) headers.set('Range', range)
        const response = await fetch(current.toString(), {
            method: 'GET',
            headers,
            redirect: 'manual',
            cache: 'no-store',
        })
        if (response.status >= 300 && response.status < 400) {
            const location = response.headers.get('location')
            if (!location) throw new Error(`Media redirect ${response.status} has no Location`)
            void response.body?.cancel()
            current = new URL(location, current)
            continue
        }
        return { response, finalUrl: current }
    }
    throw new Error('Media exceeded redirect limit')
}

export async function GET(request: NextRequest) {
    const rawTarget = request.nextUrl.searchParams.get('url')?.trim() || ''
    let target: URL
    try {
        target = new URL(rawTarget)
    } catch {
        return NextResponse.json({ error: 'Invalid media url' }, { status: 400 })
    }
    if (!isSafePublicUrl(target)) {
        return NextResponse.json({ error: 'Media url is not allowed' }, { status: 400 })
    }

    const sourceReferer = safeSourceReferer(request.nextUrl.searchParams.get('source'))
    const requestedName = request.nextUrl.searchParams.get('name')?.trim() || ''
    const range = request.headers.get('range')

    try {
        const { response: upstream, finalUrl } = await fetchMedia(target, sourceReferer, range)
        if (!upstream.ok && upstream.status !== 206) {
            void upstream.body?.cancel()
            return NextResponse.json({ error: `Upstream media request failed (${upstream.status})` }, { status: 502 })
        }
        if (!upstream.body) {
            return NextResponse.json({ error: 'Upstream media has no response body' }, { status: 502 })
        }

        const declaredLength = Number(upstream.headers.get('content-length') || 0)
        if (declaredLength > MAX_DECLARED_BYTES) {
            void upstream.body.cancel()
            return NextResponse.json({ error: 'Media exceeds size limit' }, { status: 413 })
        }

        const contentType = (upstream.headers.get('content-type') || '').split(';')[0]!.trim().toLowerCase()
        const isVideo = contentType.startsWith('video/')
            || contentType === 'application/octet-stream'
            || contentType === 'binary/octet-stream'
            || /\.(?:m4v|mov|mp4|webm)(?:$|[?#])/i.test(finalUrl.toString())
        if (!isVideo) {
            void upstream.body.cancel()
            return NextResponse.json({ error: 'Upstream response is not a downloadable video' }, { status: 415 })
        }

        const extension = extensionFromUrl(finalUrl)
        const filename = `${safeFilename(requestedName, 'media')}.${extension}`
        const headers = new Headers()
        headers.set('Content-Type', contentType.startsWith('video/') ? contentType : `video/${extension === 'mov' ? 'quicktime' : extension}`)
        headers.set('Content-Disposition', `attachment; filename*=UTF-8''${encodeURIComponent(filename)}`)
        headers.set('Cache-Control', 'private, no-store')
        headers.set('X-Robots-Tag', 'noindex, nofollow, noarchive')
        headers.set('Cross-Origin-Resource-Policy', 'same-origin')
        for (const name of ['content-length', 'content-range', 'accept-ranges', 'etag', 'last-modified']) {
            const value = upstream.headers.get(name)
            if (value) headers.set(name, value)
        }

        return new NextResponse(upstream.body, {
            status: upstream.status === 206 ? 206 : 200,
            headers,
        })
    } catch (error) {
        return NextResponse.json(
            { error: error instanceof Error ? error.message : 'Media proxy failed' },
            { status: 502 },
        )
    }
}
