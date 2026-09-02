import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

function routeSource(): string {
  return readFileSync(resolve(process.cwd(), 'src/app/api/local-media/route.ts'), 'utf8')
}

describe('Vimeo control-plane resilience', () => {
  it('uses a short timeout and bounded retries for metadata/config requests', () => {
    const source = routeSource()

    expect(source).toContain('const VIMEO_CONTROL_TIMEOUT_MS = 5_500;')
    expect(source).toContain('const VIMEO_CONTROL_ATTEMPTS = 2;')
    expect(source).toContain('AbortSignal.timeout(VIMEO_CONTROL_TIMEOUT_MS)')
    expect(source).toContain('runVimeoControlRequest')
  })

  it('retries only transient HTTP statuses and leaves media streaming outside the short timeout', () => {
    const source = routeSource()

    expect(source).toContain('return status === 408 || status === 429 || status >= 500;')
    expect(source).toContain('fetchVimeoJson<VimeoOEmbed>')
    expect(source).toContain('fetchVimeoPage(embedUrl')
    expect(source).toContain("upstream = await fetch(media.url, {")
    expect(source).not.toContain("upstream = await fetch(media.url, {\n            signal: AbortSignal.timeout")
  })
})
