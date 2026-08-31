import { ApiRequestError } from '@/lib/api-errors'
import { API_ENDPOINT_CANDIDATES, API_ENDPOINTS } from '@/lib/config'
import {
    getLastLocalEngineBridgeDiagnostic,
    parseWithLocalEngine,
} from '@/lib/local-engine-bridge'
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

function normalizeSuccessPayload(payload: UnifiedParseResult): UnifiedParseSuccessResult {
    return {
        ...payload,
        success: true,
        data: normalizeParserCapabilities(
            payload.data as unknown as Record<string, unknown>
        ) as NonNullable<UnifiedParseResult['data']>,
    } as UnifiedParseSuccessResult
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

    return normalizeSuccessPayload(payload)
}

function isVimeoUrl(value: string): boolean {
    try {
        const url = new URL(value)
        return /(^|\.)vimeo\.com$/i.test(url.hostname)
    } catch {
        return false
    }
}

async function tryVimeoNative(videoUrl: string): Promise<UnifiedParseSuccessResult | null> {
    if (!isVimeoUrl(videoUrl)) return null
    try {
        return await requestParseCandidate('/api/vimeo-native', new URLSearchParams({ url: videoUrl }))
    } catch {
        // Keep the normal Local Engine + remote fallback chain available for
        // private/password-protected Vimeo links or a temporary Vimeo player change.
        return null
    }
}

async function tryDocumentFirst(sourceUrl: string): Promise<UnifiedParseSuccessResult | null> {
    try {
        return await requestParseCandidate(
            API_ENDPOINTS.unified.documentParse,
            new URLSearchParams({ url: sourceUrl }),
        )
    } catch {
        // The document route deliberately returns UNSUPPORTED_PLATFORM for
        // video-first sites and pages without a meaningful gallery/article.
        // Network blocks and anti-bot responses also fall through so the local
        // engine can retry with the user's IP/login state.
        return null
    }
}

export async function requestUnifiedParse(videoUrl: string): Promise<UnifiedParseSuccessResult> {
    if (maybeReloadUnifiedParsePage()) {
        throw new UnifiedParseReloadError()
    }

    // Vimeo currently has an upstream yt-dlp anonymous-auth regression. Try
    // Vimeo's own player/config data first so public videos never touch browser
    // Cookie SQLite databases. This route supports both progressive MP4 and HLS.
    const vimeoNative = await tryVimeoNative(videoUrl)
    if (vimeoNative) {
        notifyTodayParseStatsChanged()
        return vimeoNative
    }

    // Product pages, image posts and articles must be inspected before a generic
    // video extractor. Otherwise one embedded product video can cause us to
    // return early and silently lose the page gallery, caption and article text.
    // The same-origin route quickly declines normal video-first platforms.
    const documentPayload = await tryDocumentFirst(videoUrl)
    if (documentPayload) {
        notifyTodayParseStatsChanged()
        return documentPayload
    }

    let localDiagnostic: string | null = null

    // Prefer the portable local engine for platforms that benefit from local
    // IP/login state. On current Chromium/Edge builds this request may require
    // explicit Local Network Access permission; the bridge layer requests
    // loopback access explicitly and records a useful diagnostic.
    if (typeof window !== 'undefined') {
        const localPayload = await parseWithLocalEngine(videoUrl)
        if (localPayload?.success && localPayload.data) {
            notifyTodayParseStatsChanged()
            return normalizeSuccessPayload(localPayload)
        }
        localDiagnostic = getLastLocalEngineBridgeDiagnostic()
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

    // Do not replace a useful local failure with the old generic remote
    // "service unavailable" message. This is especially important when the
    // browser denied localhost/LNA permission or yt-dlp returned an actionable
    // authentication error.
    if (localDiagnostic) {
        throw new ApiRequestError({
            code: 'LOCAL_ENGINE_PARSE_FAILED',
            fallbackMessage: localDiagnostic,
        })
    }

    if (lastError) throw lastError
    throw new ApiRequestError({ fallbackMessage: 'No parser endpoint is configured' })
}