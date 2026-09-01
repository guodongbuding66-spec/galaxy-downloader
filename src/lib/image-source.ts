export type PreferredRasterFormat = 'jpg' | 'png'

function isWechatImageHost(hostname: string): boolean {
    const host = hostname.toLowerCase()
    return host === 'mmbiz.qpic.cn' || host.endsWith('.mmbiz.qpic.cn')
}

/**
 * Pick the largest candidate from a standard srcset value instead of the first
 * (usually thumbnail-sized) entry.
 */
export function bestSrcsetCandidate(raw: string | null | undefined): string | null {
    if (!raw?.trim()) return null

    const candidates = raw
        .split(',')
        .map((entry) => {
            const parts = entry.trim().split(/\s+/)
            const url = parts[0] || ''
            const descriptor = parts[1] || ''
            const width = descriptor.endsWith('w') ? Number.parseFloat(descriptor.slice(0, -1)) : 0
            const density = descriptor.endsWith('x') ? Number.parseFloat(descriptor.slice(0, -1)) : 0
            return {
                url,
                width: Number.isFinite(width) ? width : 0,
                density: Number.isFinite(density) ? density : 0,
            }
        })
        .filter((candidate) => candidate.url.length > 0)

    if (!candidates.length) return null

    if (candidates.some((candidate) => candidate.width > 0)) {
        return candidates.reduce((best, candidate) => candidate.width > best.width ? candidate : best).url
    }
    if (candidates.some((candidate) => candidate.density > 0)) {
        return candidates.reduce((best, candidate) => candidate.density > best.density ? candidate : best).url
    }
    return candidates[candidates.length - 1]!.url
}

function wechatOriginalCandidate(url: URL): URL {
    const candidate = new URL(url.toString())
    const segments = candidate.pathname.split('/')
    const lastIndex = segments.length - 1
    const tail = segments[lastIndex] || ''

    // WeChat article images commonly end in /300, /640, /1080 etc. /0 asks
    // qpic for the original stored dimensions while retaining the media id.
    if (/^\d+$/.test(tail) && tail !== '0') {
        segments[lastIndex] = '0'
        candidate.pathname = segments.join('/')
    }

    // Do not explicitly force the CDN's WebP adaptation on the original
    // candidate. Keep signatures/other query parameters untouched.
    if ((candidate.searchParams.get('tp') || '').toLowerCase() === 'webp') {
        candidate.searchParams.delete('tp')
    }

    const lowerPath = candidate.pathname.toLowerCase()
    const currentFormat = (candidate.searchParams.get('wx_fmt') || '').toLowerCase()
    if (currentFormat === 'webp' || currentFormat === 'avif') {
        if (lowerPath.includes('mmbiz_jpg') || lowerPath.includes('mmbizjpeg')) {
            candidate.searchParams.set('wx_fmt', 'jpeg')
        } else if (lowerPath.includes('mmbiz_png')) {
            candidate.searchParams.set('wx_fmt', 'png')
        }
    }

    return candidate
}

/**
 * Return higher-fidelity upstream candidates first while always retaining the
 * exact parsed URL as a compatibility fallback.
 */
export function originalImageCandidates(rawUrl: string): string[] {
    let parsed: URL
    try {
        parsed = new URL(rawUrl)
    } catch {
        return [rawUrl]
    }

    const candidates: string[] = []
    if (isWechatImageHost(parsed.hostname)) {
        candidates.push(wechatOriginalCandidate(parsed).toString())
    }
    candidates.push(parsed.toString())
    return Array.from(new Set(candidates))
}

/**
 * When an upstream CDN still responds with WebP/AVIF, use the original URL as
 * a hint for the most faithful broadly-compatible fallback encoding.
 */
export function preferredRasterFormat(rawUrl: string): PreferredRasterFormat {
    try {
        const url = new URL(rawUrl)
        const format = (url.searchParams.get('wx_fmt') || '').toLowerCase()
        const path = url.pathname.toLowerCase()
        if (format === 'jpg' || format === 'jpeg' || path.includes('mmbiz_jpg') || path.includes('mmbizjpeg')) {
            return 'jpg'
        }
        if (format === 'png' || path.includes('mmbiz_png')) {
            return 'png'
        }
        if (/\.jpe?g$/i.test(path)) return 'jpg'
    } catch {
        // Fall through to lossless PNG.
    }
    return 'png'
}
