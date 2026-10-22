import { describe, expect, it } from 'vitest'

import { LOCAL_ENGINE_REQUIRED_VERSION } from '../src/lib/local-engine'
import { isLocalEngineVersionCompatible } from '../src/lib/local-engine-version-probe'

describe('Local Engine version probe policy', () => {
  it('uses the central required version without hard-coded older thresholds', () => {
    expect(LOCAL_ENGINE_REQUIRED_VERSION).toBe('0.8.0')
    expect(isLocalEngineVersionCompatible('0.7.9')).toBe(false)
    expect(isLocalEngineVersionCompatible('0.8.0')).toBe(true)
    expect(isLocalEngineVersionCompatible('0.8.1')).toBe(true)
    expect(isLocalEngineVersionCompatible('1.0.0')).toBe(true)
  })

  it('fails closed for malformed versions', () => {
    expect(isLocalEngineVersionCompatible('')).toBe(false)
    expect(isLocalEngineVersionCompatible('dev')).toBe(false)
    expect(isLocalEngineVersionCompatible('0.8')).toBe(false)
  })
})
