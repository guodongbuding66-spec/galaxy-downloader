import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

function read(path: string): string {
  return readFileSync(resolve(process.cwd(), path), 'utf8')
}

describe('Galaxy Local Engine release version synchronization', () => {
  it('keeps engine VERSION, website requirement, release tag, download API docs, and README aligned', () => {
    const engineVersion = read('local-engine/VERSION').trim()
    const localEngineSource = read('src/lib/local-engine.ts')
    const downloadRoute = read('src/app/api/local-engine/download/route.ts')
    const readme = read('README.md')

    expect(engineVersion).toMatch(/^\d+\.\d+\.\d+$/)
    expect(localEngineSource).toContain(`export const LOCAL_ENGINE_REQUIRED_VERSION = '${engineVersion}'`)
    expect(localEngineSource).toContain('export const LOCAL_ENGINE_RELEASE_TAG = `local-engine-v${LOCAL_ENGINE_REQUIRED_VERSION}`')
    expect(localEngineSource).toContain('/api/local-engine/download?version=${LOCAL_ENGINE_REQUIRED_VERSION}')

    expect(downloadRoute).toContain('requestedVersion !== LOCAL_ENGINE_REQUIRED_VERSION')
    expect(downloadRoute).toContain("headers.set('X-Galaxy-Local-Engine-Version', LOCAL_ENGINE_REQUIRED_VERSION)")

    expect(readme).toContain(`Galaxy Local Engine ${engineVersion}`)
    expect(readme).toContain(`local-engine-v${engineVersion}`)
    expect(readme).toContain(`/api/local-engine/download?version=${engineVersion}`)
    expect(readme).not.toMatch(/Galaxy Local Engine 0\.8\.0/)
  })
})
