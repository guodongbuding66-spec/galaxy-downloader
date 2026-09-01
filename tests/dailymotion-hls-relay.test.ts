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
    expect(source).toContain("if (range && !target.pathname.toLowerCase().endsWith('.m3u8')) upstreamHeaders.set('Range', range);")
    expect(source).not.toContain("if (range) upstreamHeaders.set('Range', range);")
  })

  it('keeps Dailymotion relay targets constrained to approved HTTPS media hosts', () => {
    const source = routeSource()

    expect(source).toContain("if (url.protocol !== 'https:' || !allowedDailymotionHost(url.hostname)) return null;")
    expect(source).toContain("'dmcdn.net'")
    expect(source).toContain("'dailymotion.com'")
    expect(source).toContain("'dailymotioncdn.com'")
  })
})
