import { describe, expect, it } from 'vitest'

import {
  getBilibiliDanmakuFormatCapability,
  normalizeBilibiliDanmakuFormatCapability,
} from '../src/lib/bilibili-danmaku-capability'

describe('Bilibili danmaku format capability', () => {
  it('fails closed to native XML for missing, invalid or older engine status payloads', () => {
    expect(normalizeBilibiliDanmakuFormatCapability(null)).toEqual(['xml'])
    expect(normalizeBilibiliDanmakuFormatCapability({ ok: false, bilibiliDanmakuFormats: ['ass'] })).toEqual(['xml'])
    expect(normalizeBilibiliDanmakuFormatCapability({ ok: true })).toEqual(['xml'])
    expect(normalizeBilibiliDanmakuFormatCapability({ ok: true, bilibiliDanmakuFormats: 'ass,json' })).toEqual(['xml'])
  })

  it('accepts only explicitly advertised supported formats', () => {
    expect(normalizeBilibiliDanmakuFormatCapability({
      ok: true,
      bilibiliDanmakuFormats: ['ASS', 'json', 'ass', 'srt'],
    })).toEqual(['ass', 'json'])
  })

  it('tries both loopback hostnames and returns the first explicit capability', async () => {
    const urls: string[] = []
    const fetcher = (async (input: RequestInfo | URL) => {
      urls.push(String(input))
      if (urls.length === 1) throw new Error('localhost unavailable')
      return new Response(JSON.stringify({
        ok: true,
        bilibiliDanmakuFormats: ['xml', 'ass', 'json'],
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }) as typeof fetch

    await expect(getBilibiliDanmakuFormatCapability(fetcher)).resolves.toEqual(['xml', 'ass', 'json'])
    expect(urls).toEqual([
      'http://localhost:17836/status',
      'http://127.0.0.1:17836/status',
    ])
  })

  it('returns XML only when every loopback attempt fails', async () => {
    const fetcher = (async () => {
      throw new Error('offline')
    }) as typeof fetch

    await expect(getBilibiliDanmakuFormatCapability(fetcher)).resolves.toEqual(['xml'])
  })
})
