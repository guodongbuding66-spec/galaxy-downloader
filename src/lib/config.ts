/**
 * API Configuration
 */

const DEFAULT_DEV_API_BASE_URL = 'http://localhost:8788'
const DEFAULT_PROD_API_BASE_URL = 'https://downloader-api.bhwa233.com'
const FIRST_PARTY_LOCAL_PARSE_ENDPOINT = '/api/local-parse'
const FIRST_PARTY_PARSE_STATS_ENDPOINT = '/api/site-stats'

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
        // Keep Galaxy usage statistics first-party. Do not route this through
        // the shared parser backend, otherwise the UI displays someone else's totals.
        today: FIRST_PARTY_PARSE_STATS_ENDPOINT,
    },
} as const

/**
 * Ordered media backend candidates.
 *
 * Parsing tries Galaxy's same-origin lightweight parser first. Unsupported
 * platforms then continue to the existing shared/container backends. Keeping
 * one first-party endpoint avoids route-registration differences between
 * local vinext builds and the deployed Cloudflare Worker.
 */
export const API_ENDPOINT_CANDIDATES = {
    unified: {
        parse: parseEndpointCandidates(),
        download: endpointCandidates('/api/download'),
    },
} as const
