import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  fetchVimeoControlJson,
  fetchVimeoControlPage,
  VIMEO_CONTROL_ATTEMPTS,
  VIMEO_CONTROL_TIMEOUT_MS,
} from '../src/lib/vimeo-control'

function source(path: string): string {
  return readFileSync(resolve(process.cwd(), path), 'utf8')
}

function mockResponse(status: number, jsonValue: unknown = {}): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    body: null,
    json: vi.fn(async () => jsonValue),
    text: vi.fn(async () => ''),
  } as unknown as Response
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Vimeo control-plane resilience', () => {
  it('keeps control requests short and bounded', () => {
    expect(VIMEO_CONTROL_TIMEOUT_MS).toBe(5_500)
    expect(VIMEO_CONTROL_ATTEMPTS).toBe(2)
  })

  it('retries a transient 503 once and then succeeds', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(mockResponse(503))
      .mockResolvedValueOnce(mockResponse(200, { ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(fetchVimeoControlJson<{ ok: boolean }>('https://vimeo.com/test', {}))
      .resolves.toEqual({ ok: true })
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('does not retry a non-transient 404 JSON response', async () => {
    const fetchMock = vi.fn().mockResolvedValue(mockResponse(404))
    vi.stubGlobal('fetch', fetchMock)

    await expect(fetchVimeoControlJson('https://vimeo.com/missing', {}))
      .rejects.toThrow('HTTP 404')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('returns a non-transient player-page 404 without retrying', async () => {
    const fetchMock = vi.fn().mockResolvedValue(mockResponse(404))
    vi.stubGlobal('fetch', fetchMock)

    await expect(fetchVimeoControlPage('https://player.vimeo.com/missing', {}))
      .resolves.toEqual({ ok: false, status: 404, text: '' })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('uses the shared helper in the production-smoke parser and media resolver', () => {
    const nativeSource = source('src/app/api/vimeo-native/route.ts')
    const mediaSource = source('src/app/api/vimeo-media/route.ts')

    expect(nativeSource).toContain("from '@/lib/vimeo-control'")
    expect(nativeSource).toContain('fetchVimeoControlPage(embedUrl')
    expect(mediaSource).toContain("from '@/lib/vimeo-control'")
    expect(mediaSource).toContain('fetchVimeoControlPage(embedUrl')
  })

  it('does not apply the short control timeout to actual media streaming', () => {
    const mediaSource = source('src/app/api/vimeo-media/route.ts')

    expect(mediaSource).toContain("upstream = await fetch(target.toString(), {")
    expect(mediaSource).not.toContain("upstream = await fetch(target.toString(), {\n      signal: AbortSignal.timeout")
  })
})
