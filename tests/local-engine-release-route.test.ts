import { afterEach, describe, expect, it, vi } from 'vitest'

import { GET } from '../src/app/api/local-engine/download/route'
import {
  LOCAL_ENGINE_GITHUB_URL,
  LOCAL_ENGINE_REQUIRED_VERSION,
} from '../src/lib/local-engine'

describe('Local Engine release relay', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('rejects a release version that does not match the running website', async () => {
    const upstream = vi.fn()
    vi.stubGlobal('fetch', upstream)

    const response = await GET(new Request('https://galaxy.example/api/local-engine/download?version=0.7.0'))
    expect(response.status).toBe(400)
    expect(upstream).not.toHaveBeenCalled()
    await expect(response.json()).resolves.toMatchObject({
      success: false,
      requiredVersion: LOCAL_ENGINE_REQUIRED_VERSION,
    })
  })

  it('proxies only the exact pinned GitHub release asset', async () => {
    const upstream = vi.fn(async () => new Response('zip-data', {
      status: 200,
      headers: {
        'content-type': 'application/zip',
        'content-length': '8',
        etag: '"galaxy-test"',
      },
    }))
    vi.stubGlobal('fetch', upstream)

    const response = await GET(new Request(
      `https://galaxy.example/api/local-engine/download?version=${LOCAL_ENGINE_REQUIRED_VERSION}`,
    ))

    expect(response.status).toBe(200)
    expect(upstream).toHaveBeenCalledTimes(1)
    expect(upstream.mock.calls[0]?.[0]).toBe(LOCAL_ENGINE_GITHUB_URL)
    expect(LOCAL_ENGINE_GITHUB_URL).not.toContain('/releases/latest/')
    expect(response.headers.get('x-galaxy-local-engine-version')).toBe(LOCAL_ENGINE_REQUIRED_VERSION)
    expect(response.headers.get('content-disposition')).toContain('GalaxyLocalEngine-Windows.zip')
    expect(await response.text()).toBe('zip-data')
  })
})
