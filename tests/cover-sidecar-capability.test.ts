import { describe, expect, it, vi } from 'vitest'

import {
  getCoverSidecarCapability,
  normalizeCoverSidecarCapability,
} from '../src/lib/cover-sidecar-capability'

describe('cover sidecar Local Engine capability', () => {
  it('unlocks only an explicit successful capability', () => {
    expect(normalizeCoverSidecarCapability(null)).toBe(false)
    expect(normalizeCoverSidecarCapability({ ok: false, coverSidecar: true })).toBe(false)
    expect(normalizeCoverSidecarCapability({ ok: true })).toBe(false)
    expect(normalizeCoverSidecarCapability({ ok: true, coverSidecar: false })).toBe(false)
    expect(normalizeCoverSidecarCapability({ ok: true, coverSidecar: true })).toBe(true)
  })

  it('falls back to the alternate loopback host before enabling the capability', async () => {
    const fetcher = vi.fn<typeof fetch>()
      .mockRejectedValueOnce(new TypeError('localhost unavailable'))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, coverSidecar: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }))

    await expect(getCoverSidecarCapability(fetcher)).resolves.toBe(true)
    expect(fetcher).toHaveBeenCalledTimes(2)
    expect(String(fetcher.mock.calls[0]?.[0])).toContain('localhost:17836/status')
    expect(String(fetcher.mock.calls[1]?.[0])).toContain('127.0.0.1:17836/status')
  })

  it('fails closed for older, malformed, HTTP-error and offline engines', async () => {
    const oldEngine = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    )
    await expect(getCoverSidecarCapability(oldEngine)).resolves.toBe(false)

    const httpFailure = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(new Response('', { status: 503 }))
      .mockResolvedValueOnce(new Response('', { status: 503 }))
    await expect(getCoverSidecarCapability(httpFailure)).resolves.toBe(false)

    const offline = vi.fn<typeof fetch>().mockRejectedValue(new TypeError('offline'))
    await expect(getCoverSidecarCapability(offline)).resolves.toBe(false)
  })
})
