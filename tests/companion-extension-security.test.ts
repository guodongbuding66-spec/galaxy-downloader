import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('Galaxy Companion privacy boundaries', () => {
  it('keeps broad site access optional instead of mandatory', () => {
    const manifest = JSON.parse(
      readFileSync(resolve(process.cwd(), 'companion-extension/manifest.json'), 'utf8'),
    ) as {
      host_permissions?: string[]
      optional_host_permissions?: string[]
    }

    expect(manifest.host_permissions).not.toContain('<all_urls>')
    expect(manifest.optional_host_permissions).toContain('http://*/*')
    expect(manifest.optional_host_permissions).toContain('https://*/*')
  })

  it('never exposes a cookie-reading method to page JavaScript', () => {
    const bridge = readFileSync(resolve(process.cwd(), 'src/lib/local-engine.ts'), 'utf8')
    const contentScript = readFileSync(resolve(process.cwd(), 'companion-extension/content.js'), 'utf8')

    expect(bridge).not.toContain("'engine.cookies'")
    expect(contentScript).not.toContain("'engine.cookies'")
  })
})
