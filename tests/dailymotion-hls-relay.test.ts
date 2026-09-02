import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

function routeSource(): string {
  return readFileSync(resolve(process.cwd(), 'src/app/api/local-media/route.ts'), 'utf8')
}

describe('Dailymotion HLS relay', () => {
  it('does not forward browser Range headers to m3u8 playlists', () => {
    const source = routeSource()

    expect(source).toContain("const range = request.headers.get('range');")
    expect(source).toContain("if (range && !target.pathname.toLowerCase().endsWith('.m3u8'))")
    expect(source).toContain("headers.set('Range', range);")
  })

  it('randomizes the HLS HTTP header fingerprint and retries blocked upstream responses', () => {
    const source = routeSource()

    expect(source).toContain('const DAILYMOTION_HLS_ATTEMPTS = 3;')
    expect(source).toContain('function dailymotionBlockbusterHeaders(')
    expect(source).toContain('const randomHeaderCount = 2 + Math.floor(Math.random() * 7);')
    expect(source).toContain('headers.set(randomDailymotionLetters(8, 16), randomDailymotionLetters(8, 24));')
    expect(source).toContain('return status === 403 || status === 408 || status === 429 || status >= 500;')
    expect(source).toContain('fetchDailymotionHlsResource(target, id, range)')
  })

  it('tries neutral headers before Dailymotion referer/origin fallback combinations', () => {
    const source = routeSource()

    expect(source).toContain("if (attempt === 1) {")
    expect(source).toContain("headers.set('Referer', `https://www.dailymotion.com/video/${id}`);")
    expect(source).toContain("headers.set('Origin', 'https://www.dailymotion.com');")
    expect(source).toContain("headers.set('Referer', 'https://www.dailymotion.com/');")
  })

  it('keeps Dailymotion relay targets constrained to approved HTTPS media hosts', () => {
    const source = routeSource()

    expect(source).toContain("if (url.protocol !== 'https:' || !allowedDailymotionHost(url.hostname)) return null;")
    expect(source).toContain("'dmcdn.net'")
    expect(source).toContain("'dailymotion.com'")
    expect(source).toContain("'dailymotioncdn.com'")
  })
})
