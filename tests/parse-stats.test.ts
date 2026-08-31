import { afterEach, describe, expect, it, vi } from 'vitest'
import {
    fetchTodayParseStats,
    notifyTodayParseStatsChanged,
    TODAY_PARSE_STATS_REFRESH_EVENT,
} from '@/lib/parse-stats'

function mockFetch(response: unknown, options?: { ok?: boolean }) {
    const fetchMock = vi.fn(async () => ({
        ok: options?.ok ?? true,
        json: async () => response,
    }))

    vi.stubGlobal('fetch', fetchMock)
    return fetchMock
}

describe('fetchTodayParseStats', () => {
    afterEach(() => {
        vi.unstubAllGlobals()
        vi.restoreAllMocks()
    })

    it('returns stats on a successful response', async () => {
        const payload = {
            date: '2026-08-13',
            timezone: 'UTC+08:00',
            windowStart: '2026-08-12T16:00:00.000Z',
            windowEnd: '2026-08-13T16:00:00.000Z',
            count: 1234,
            totalCount: 5678,
        }
        const fetchMock = mockFetch({ success: true, data: payload })

        await expect(fetchTodayParseStats()).resolves.toEqual(payload)
        expect(fetchMock).toHaveBeenCalledWith('/api/site-stats', {
            signal: undefined,
            cache: 'no-store',
        })
    })

    it('adds a cache buster for an immediate refresh', async () => {
        const fetchMock = mockFetch({ success: true, data: {
            date: '2026-08-13',
            timezone: 'UTC+08:00',
            windowStart: '2026-08-12T16:00:00.000Z',
            windowEnd: '2026-08-13T16:00:00.000Z',
            count: 1234,
        } })

        await fetchTodayParseStats({ cacheBuster: 'parse-complete' })

        expect(fetchMock).toHaveBeenCalledWith(
            '/api/site-stats?refresh=parse-complete',
            expect.any(Object)
        )
    })

    it('records a successful parse with the first-party endpoint and refreshes the card', async () => {
        const fetchMock = mockFetch({ success: true })
        const dispatchEvent = vi.fn()

        class TestCustomEvent {
            readonly type: string
            readonly detail: unknown

            constructor(type: string, options?: { detail?: unknown }) {
                this.type = type
                this.detail = options?.detail
            }
        }

        vi.stubGlobal('window', { dispatchEvent })
        vi.stubGlobal('CustomEvent', TestCustomEvent)

        notifyTodayParseStatsChanged()

        await vi.waitFor(() => {
            expect(fetchMock).toHaveBeenCalledWith('/api/site-stats', {
                method: 'POST',
                cache: 'no-store',
            })
            expect(dispatchEvent).toHaveBeenCalledTimes(1)
        })

        const event = dispatchEvent.mock.calls[0]?.[0] as TestCustomEvent
        expect(event.type).toBe(TODAY_PARSE_STATS_REFRESH_EVENT)
    })

    it('returns null on a non-ok response', async () => {
        mockFetch({ success: false }, { ok: false })

        await expect(fetchTodayParseStats()).resolves.toBeNull()
    })

    it('returns null when the payload shape is unexpected', async () => {
        mockFetch({ success: true, data: { date: '2026-08-13', count: 'many' } })

        await expect(fetchTodayParseStats()).resolves.toBeNull()
    })

    it('returns null when the request throws', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => {
            throw new Error('network down')
        }))

        await expect(fetchTodayParseStats()).resolves.toBeNull()
    })
})
