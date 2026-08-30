/**
 * API Configuration
 */

const DEFAULT_DEV_API_BASE_URL = 'http://localhost:8788'
const DEFAULT_PROD_API_BASE_URL = 'https://downloader-api.bhwa233.com'
const FIRST_PARTY_LOCAL_PARSE_ENDPOINT = '/api/local-parse'

function normalizeBaseUrl(value: string): string {
    return value.endsWith('/') ? value.slice(0, -1) : value
}

function resolvePublicApiBaseUrl(): string {
    const configuredBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL?.trim()
    if (configuredBaseUrl) {
        return normalizeBaseUrl(configuredBaseUrl)
    }

    if (process.env.NODE_ENV === 'development') {
        return DEFAULT_DEV_API_BASE_URL
    }

    if (process.env.NODE_ENV === 'production') {
        return DEFAULT_PROD_API_BASE_URL
    }

    return ''
}

function resolveContainerApiBaseUrl(): string {
    const value = process.env.NEXT_PUBLIC_CONTAINER_API_BASE_URL?.trim()
    if (!value) return ''
    if (!/^https?:\/\//i.test(value)) return ''
    return normalizeBaseUrl(value)
}

function buildApiUrl(pathname: string, baseUrl = resolvePublicApiBaseUrl()): string {
    const normalizedPathname = pathname.startsWith('/') ? pathname : `/${pathname}`

    if (!baseUrl) {
        return normalizedPathname
    }

    return new URL(normalizedPathname, `${baseUrl}/`).toString()
}

function endpointCandidates(pathname: string): string[] {
    const primary = buildApiUrl(pathname)
    const containerBase = resolveContainerApiBaseUrl()
    const candidates = [primary]
    if (containerBase) {
        candidates.push(buildApiUrl(pathname, containerBase))
    }
    return [...new Set(candidates)]
}

function parseEndpointCandidates(): string[] {
    return [
        FIRST_PARTY_LOCAL_PARSE_ENDPOINT,
        ...endpointCandidates('/api/parse'),
    ].filter((value, index, list) => list.indexOf(value) === index)
}

/**
 * Primary API endpoints. These keep the existing production behavior intact.
 */
export const API_ENDPOINTS = {
    unified: {
        parse: buildApiUrl('/api/parse'),
        download: buildApiUrl('/api/download'),
        play: buildApiUrl('/api/play'),
    },
    feedback: buildApiUrl('/api/feedback'),
    stats: {
        today: buildApiUrl('/api/stats/today'),
    },
} as const

/**
 * Ordered media backend candidates.
 *
 * Parsing tries Galaxy's same-origin lightweight parser first. It handles a
 * small set of public platforms without API keys and deliberately returns an
 * error for everything else; requestUnifiedParse then falls back to the
 * existing shared/container backends. Download candidates remain unchanged.
 */
export const API_ENDPOINT_CANDIDATES = {
    unified: {
        parse: parseEndpointCandidates(),
        download: endpointCandidates('/api/download'),
    },
} as const
