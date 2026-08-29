import { describe, expect, it } from 'vitest'

import {
  detectLocalProcessingCapabilities,
  GALAXY_LOCAL_ENGINE_PROTOCOL_VERSION,
  isGalaxyCompanionEnvelope,
} from '../src/lib/local-engine'

describe('local media engine capabilities', () => {
  it('enables multithread ffmpeg only with SharedArrayBuffer and cross-origin isolation', () => {
    expect(detectLocalProcessingCapabilities({
      WebAssembly: {},
      SharedArrayBuffer: {},
      crossOriginIsolated: true,
      navigator: {
        storage: { getDirectory() {} },
        serviceWorker: {},
        wakeLock: {},
      },
    })).toEqual({
      webAssembly: true,
      sharedArrayBuffer: true,
      crossOriginIsolated: true,
      multiThreadFFmpeg: true,
      opfs: true,
      serviceWorker: true,
      wakeLock: true,
    })

    expect(detectLocalProcessingCapabilities({
      WebAssembly: {},
      SharedArrayBuffer: {},
      crossOriginIsolated: false,
      navigator: {},
    }).multiThreadFFmpeg).toBe(false)
  })

  it('reports missing browser features without throwing', () => {
    expect(detectLocalProcessingCapabilities({})).toEqual({
      webAssembly: false,
      sharedArrayBuffer: false,
      crossOriginIsolated: false,
      multiThreadFFmpeg: false,
      opfs: false,
      serviceWorker: false,
      wakeLock: false,
    })
  })

  it('accepts only Galaxy Companion response envelopes', () => {
    expect(isGalaxyCompanionEnvelope({
      source: 'galaxy-companion',
      protocolVersion: GALAXY_LOCAL_ENGINE_PROTOCOL_VERSION,
      requestId: 'req-1',
      type: 'response',
      ok: true,
    })).toBe(true)

    expect(isGalaxyCompanionEnvelope({
      source: 'other-extension',
      protocolVersion: 1,
      requestId: 'req-1',
      type: 'response',
    })).toBe(false)

    expect(isGalaxyCompanionEnvelope(null)).toBe(false)
  })
})
