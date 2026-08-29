import { ApiRequestError } from '@/lib/api-errors'
import { API_ENDPOINT_CANDIDATES } from '@/lib/config'
import { normalizeParserCapabilities } from '@/lib/parser-capabilities'
import { notifyTodayParseStatsChanged } from '@/lib/parse-stats'
import type { UnifiedParseResult } from '@/lib/types'

const UNIFIED_PARSE_RELOAD_THRESHOLD = 60

export type UnifiedParseSuccessResult = UnifiedParseResult & {
    success: true
    data: NonNullable<UnifiedParseResult['data']>
}

let unifiedParseAttemptCount = 0

export class UnifiedParseReloadError extends Error {
    constructor() {
        super('Unified parse threshold reached')
        this.name = 'UnifiedParseReloadError'
    }
}

export function resetUnifiedParseAttemptCountForTests() {
    unifiedParseAttemptCount = 0
}

function maybeReloadUnifiedParsePage(): boolean {
    if (typeof window === 'undefined') {
        return false
    }

    if (unifiedParseAttemptCount >= UNIFIED_PARSE_RELOAD_THRESHOLD) {
        window.location.reload()
        return true
    }

    unifiedParseAttemptCount += 1
    return false
}

async function requestParseCandidate(endpoint: string, params: URLSearchParams): Promise<UnifiedParseSuccessResult> {
    const separator = endpoint.includes('?') ? '&' : '?'
    const requestUrl = `${endpoint}${separator}${params.toString()}`
    let response: Response

    try {
        response = await fetch(requestUrl, {
            method: 'GET',
            cache: 'no-store',
        })
    } catch (error) {
        throw new ApiRequestError({
            fallbackMessage: error instanceof Error ? error.message : 'Parser request failed',
        })
    }

    let payload: UnifiedParseResult | null = null
    try {
        payload = await response.json() as UnifiedParseResult
    } catch {
        throw new ApiRequestError({
            status: response.status,
        })
    }

    if (!response.ok || !payload?.success || !payload.data) {
        throw new ApiRequestError({
            code: payload?.code,
            status: payload?.status ?? response.status,
            requestId: payload?.requestId,
            details: payload?.details,
            fallbackMessage: payload?.error || payload?.message,
        })
    }

    return {
        ...payload,
        data: normalizeParserCapabilities(
            payload.data as unknown as Record<string, unknown>
        ) as NonNullable<UnifiedParseResult['data']>,
    } as UnifiedParseSuccessResult
}

export async function requestUnifiedParse(videoUrl: string): Promise<UnifiedParseSuccessResult> {
    if (maybeReloadUnifiedParsePage()) {
        throw new UnifiedParseReloadError()
    }

    const params = new URLSearchParams({ url: videoUrl })
    let lastError: unknown = null

    for (const endpoint of API_ENDPOINT_CANDIDATES.unified.parse) {
        try {
            const payload = await requestParseCandidate(endpoint, params)
            notifyTodayParseStatsChanged()
            return payload
        } catch (error) {
            lastError = error
        }
    }

    if (lastError) throw lastError
    throw new ApiRequestError({ fallbackMessage: 'No parser endpoint is configured' })
}
