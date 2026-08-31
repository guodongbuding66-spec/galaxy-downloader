import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { UnifiedParseResult } from '../src/lib/types.ts'
import {
    UnifiedParseReloadError,
    requestUnifiedParse,
    resetUnifiedParseAttemptCountForTests,
} from '../src/lib/unified-parse.ts'
import { TODAY_PARSE_STATS_REFRESH_EVENT } from '../src/lib/parse-stats.ts'

const responsePayload = {
    success: true,
    data: {
        title: 'Parsed title',
        platform: 'youtube',
        downloadAudioUrl: null,
        downloadVideoUrl: null,
        originDownloadVideoUrl: null,
        url: 'https://example.com/watch?v=1',
    },
} satisfies UnifiedParseResult

describe('requestUnifiedParse reload guard', () => {
    const reload = vi.fn()
    const dispatchEvent = vi.fn()
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(responsePayload), {
        status: 200,
        headers: {
            'content-type': 'application/json',
        },
    }))

    const parseRequestCount = () => fetchMock.mock.calls.filter(([input]) => (
        typeof input === 'string' && !input.startsWith('/api/site-stats')
    )).length

    const statsRequestCount = () => fetchMock.mock.calls.filter(([input]) => (
        typeof input === 'string' && input.startsWith('/api/site-stats')
    )).length

    beforeEach(() => {
        resetUnifiedParseAttemptCountForTests()
        reload.mockClear()
        dispatchEvent.mockClear()
        fetchMock.mockClear()

        vi.stubGlobal('window', {
            location: {
                reload,
            },
            dispatchEvent,
        } as never)

        vi.stubGlobal('fetch', fetchMock as never)
    })

    afterEach(() => {
        vi.unstubAllGlobals()
        resetUnifiedParseAttemptCountForTests()
    })

    it('reloads on the 61st parse attempt before sending another parse request', async () => {
        for (let index = 0; index < 60; index += 1) {
            await requestUnifiedParse('https://example.com/watch?v=1')
        }

        expect(parseRequestCount()).toBe(60)
        expect(statsRequestCount()).toBe(60)

        await expect(requestUnifiedParse('https://example.com/watch?v=1')).rejects.toBeInstanceOf(
            UnifiedParseReloadError
        )

        expect(reload).toHaveBeenCalledTimes(1)
        expect(parseRequestCount()).toBe(60)
        expect(statsRequestCount()).toBe(60)
    })

    it('records and refreshes today stats after a successful parse', async () => {
        await requestUnifiedParse('https://example.com/watch?v=1')

        expect(parseRequestCount()).toBe(1)
        expect(statsRequestCount()).toBe(1)

        await vi.waitFor(() => {
            expect(dispatchEvent).toHaveBeenCalledTimes(1)
        })
        expect(dispatchEvent.mock.calls[0][0]).toBeInstanceOf(CustomEvent)
        expect(dispatchEvent.mock.calls[0][0].type).toBe(TODAY_PARSE_STATS_REFRESH_EVENT)
    })
})
