import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  DAILYMOTION_HLS_ATTEMPTS,
  dailymotionHlsHeaders,
  fetchDailymotionHlsResource,
  retryableDailymotionStatus,
} from '../src/lib/dailymotion-hls'

function routeSource(): string {
  return readFileSync(resolve(process.cwd(), 'src/app/api/local-media/route.ts'), 'utf8')
}

function mockResponse(status: number): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    body: { cancel: vi.fn(async () => undefined) },
  } as unknown as Response
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Dailymotion HLS relay', () => {
  it('keeps retries bounded and treats production blocking statuses as transient', () => {
    expect(DAILYMOTION_HLS_ATTEMPTS).toBe(3)
    expect(retryableDailymotionStatus(403)).toBe(true)
    expect(retryableDailymotionStatus(408)).toBe(true)
    expect(retryableDailymotionStatus(429)).toBe(true)
    expect(retryableDailymotionStatus(503)).toBe(true)
    expect(retryableDailymotionStatus(404)).toBe(false)
  })

  it('does not forward Range to m3u8 playlists but keeps it for media segments', () => {
    const playlist = dailymotionHlsHeaders({
      id: 'x123',
      target: new URL('https://proxy.dmcdn.net/master.m3u8'),
      range: 'bytes=0-99',
      userAgent: 'Galaxy-Test',
    }, 0)
    expect(playlist.get('Range')).toBeNull()

    const segment = dailymotionHlsHeaders({
      id: 'x123',
      target: new URL('https://proxy.dmcdn.net/segment.ts'),
      range: 'bytes=0-99',
      userAgent: 'Galaxy-Test',
    }, 0)
    expect(segment.get('Range')).toBe('bytes=0-99')
  })

  it('uses controlled Dailymotion referer/origin values only', () => {
    const options = {
      id: 'x123',
      target: new URL('https://proxy.dmcdn.net/master.m3u8'),
      range: null,
      userAgent: 'Galaxy-Test',
    }
    const first = dailymotionHlsHeaders(options, 0)
    const fallback = dailymotionHlsHeaders(options, 1)
    expect(first.get('Referer')).toBe('https://www.dailymotion.com/video/x123')
    expect(first.get('Origin')).toBe('https://www.dailymotion.com')
    expect(fallback.get('Referer')).toBe('https://www.dailymotion.com/')
    expect(fallback.get('Origin')).toBe('https://www.dailymotion.com')
  })

  it('retries a blocked 403 and succeeds on the next response', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(mockResponse(403))
      .mockResolvedValueOnce(mockResponse(200))
    vi.stubGlobal('fetch', fetchMock)

    await expect(fetchDailymotionHlsResource({
      id: 'x123',
      target: new URL('https://proxy.dmcdn.net/master.m3u8'),
      range: null,
      userAgent: 'Galaxy-Test',
    })).resolves.toMatchObject({ status: 200 })
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('does not retry deterministic 404 responses', async () => {
    const fetchMock = vi.fn().mockResolvedValue(mockResponse(404))
    vi.stubGlobal('fetch', fetchMock)

    await expect(fetchDailymotionHlsResource({
      id: 'x123',
      target: new URL('https://proxy.dmcdn.net/master.m3u8'),
      range: null,
      userAgent: 'Galaxy-Test',
    })).resolves.toMatchObject({ status: 404 })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('keeps Dailymotion relay targets constrained to approved HTTPS media hosts', () => {
    const source = routeSource()
    expect(source).toContain("if (url.protocol !== 'https:' || !allowedDailymotionHost(url.hostname)) return null;")
    expect(source).toContain("'dmcdn.net'")
    expect(source).toContain("'dailymotion.com'")
    expect(source).toContain("'dailymotioncdn.com'")
  })

  it('routes production HLS fetching through the bounded recovery helper', () => {
    const source = routeSource()
    expect(source).toContain("from '@/lib/dailymotion-hls'")
    expect(source).toContain('fetchDailymotionHlsResource({')
    expect(source).not.toContain("if (range && !target.pathname.toLowerCase().endsWith('.m3u8')) upstreamHeaders.set('Range', range);")
  })
})
