import { describe, expect, it, vi } from 'vitest'

import {
  getNfoSidecarCapability,
  normalizeNfoSidecarCapability,
} from '../src/lib/nfo-sidecar-capability'

describe('NFO sidecar Local Engine capability', () => {
  it('unlocks only an explicit successful capability', () => {
    expect(normalizeNfoSidecarCapability(null)).toBe(false)
    expect(normalizeNfoSidecarCapability({ ok: false, nfoSidecar: true })).toBe(false)
    expect(normalizeNfoSidecarCapability({ ok: true })).toBe(false)
    expect(normalizeNfoSidecarCapability({ ok: true, nfoSidecar: false })).toBe(false)
    expect(normalizeNfoSidecarCapability({ ok: true, nfoSidecar: true })).toBe(true)
  })

  it('falls back to the alternate loopback host before enabling the capability', async () => {
    const fetcher = vi.fn<typeof fetch>()
      .mockRejectedValueOnce(new TypeError('localhost unavailable'))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, nfoSidecar: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }))

    await expect(getNfoSidecarCapability(fetcher)).resolves.toBe(true)
    expect(fetcher).toHaveBeenCalledTimes(2)
    expect(String(fetcher.mock.calls[0]?.[0])).toContain('localhost:17836/status')
    expect(String(fetcher.mock.calls[1]?.[0])).toContain('127.0.0.1:17836/status')
  })

  it('fails closed for older, malformed, HTTP-error and offline engines', async () => {
    const oldEngine = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    )
    await expect(getNfoSidecarCapability(oldEngine)).resolves.toBe(false)

    const malformed = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, nfoSidecar: 'true' }), { status: 200 }),
    )
    await expect(getNfoSidecarCapability(malformed)).resolves.toBe(false)

    const httpFailure = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(new Response('', { status: 503 }))
      .mockResolvedValueOnce(new Response('', { status: 503 }))
    await expect(getNfoSidecarCapability(httpFailure)).resolves.toBe(false)

    const offline = vi.fn<typeof fetch>().mockRejectedValue(new TypeError('offline'))
    await expect(getNfoSidecarCapability(offline)).resolves.toBe(false)
  })
})
