import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('local browser processing headers', () => {
  it('keeps the Worker cross-origin isolated with a compatibility fallback path', () => {
    const source = readFileSync(resolve(process.cwd(), 'worker/index.ts'), 'utf8')

    expect(source).toContain('Cross-Origin-Opener-Policy')
    expect(source).toContain('same-origin')
    expect(source).toContain('Cross-Origin-Embedder-Policy')
    expect(source).toContain('credentialless')
    expect(source).toContain('Origin-Agent-Cluster')
  })
})
