import { describe, expect, it } from 'vitest'

import {
  LOCAL_ENGINE_GITHUB_URL,
  LOCAL_ENGINE_RELEASE_TAG,
  LOCAL_ENGINE_RELEASE_URL,
  LOCAL_ENGINE_REQUIRED_VERSION,
  canProcessMediaLocally,
  detectLocalProcessingCapabilities,
  shouldUseFileBackedInputs,
} from '../src/lib/local-engine'

describe('local media engine capabilities', () => {
  it('uses the multithread profile only with SharedArrayBuffer and cross-origin isolation', () => {
    const capabilities = detectLocalProcessingCapabilities({
      WebAssembly: {},
      SharedArrayBuffer: {},
      crossOriginIsolated: true,
      navigator: {
        storage: { getDirectory() {} },
        serviceWorker: {},
        wakeLock: {},
      },
    })

    expect(capabilities).toEqual({
      webAssembly: true,
      sharedArrayBuffer: true,
      crossOriginIsolated: true,
      multiThreadFFmpeg: true,
      opfs: true,
      serviceWorker: true,
      wakeLock: true,
      profile: 'multi-thread',
    })
    expect(canProcessMediaLocally(capabilities)).toBe(true)
    expect(shouldUseFileBackedInputs(capabilities)).toBe(true)
  })

  it('falls back to the single-thread profile without cross-origin isolation', () => {
    const capabilities = detectLocalProcessingCapabilities({
      WebAssembly: {},
      SharedArrayBuffer: {},
      crossOriginIsolated: false,
      navigator: {},
    })

    expect(capabilities.profile).toBe('single-thread')
    expect(capabilities.multiThreadFFmpeg).toBe(false)
    expect(canProcessMediaLocally(capabilities)).toBe(true)
    expect(shouldUseFileBackedInputs(capabilities)).toBe(false)
  })

  it('reports unsupported browsers without throwing', () => {
    const capabilities = detectLocalProcessingCapabilities({})

    expect(capabilities).toEqual({
      webAssembly: false,
      sharedArrayBuffer: false,
      crossOriginIsolated: false,
      multiThreadFFmpeg: false,
      opfs: false,
      serviceWorker: false,
      wakeLock: false,
      profile: 'unsupported',
    })
    expect(canProcessMediaLocally(capabilities)).toBe(false)
  })

  it('pins the website and GitHub mirror to the exact required Local Engine release', () => {
    expect(LOCAL_ENGINE_REQUIRED_VERSION).toBe('0.12.0')
    expect(LOCAL_ENGINE_RELEASE_TAG).toBe('local-engine-v0.12.0')
    expect(LOCAL_ENGINE_RELEASE_URL).toContain('version=0.12.0')
    expect(LOCAL_ENGINE_GITHUB_URL).toContain('/releases/download/local-engine-v0.12.0/')
    expect(LOCAL_ENGINE_GITHUB_URL).not.toContain('/releases/latest/')
  })
})
