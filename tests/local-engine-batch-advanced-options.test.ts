import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

import {
  createDefaultLocalEngineAdvancedOptions,
  resolveLocalEngineAdvancedJobOptions,
  type LocalEngineDanmakuFormat,
} from '../src/lib/local-engine'
import { normalizeLocalEngineBridgeStatusPayload } from '../src/lib/local-engine-bridge'

describe('shared Local Engine advanced media options', () => {
  it('keeps every advanced feature opt-in by default and returns isolated collections', () => {
    const first = createDefaultLocalEngineAdvancedOptions()
    const second = createDefaultLocalEngineAdvancedOptions()

    expect(first).toEqual({
      segmentStart: '',
      segmentEnd: '',
      splitChapters: false,
      subtitleMode: 'both',
      subtitleLanguages: [],
      audioLanguages: [],
      sponsorBlockCategories: [],
      useAria2c: false,
      includeDanmaku: false,
      danmakuFormats: ['xml'],
      keepCoverSidecar: false,
      includeNfo: false,
    })

    first.subtitleLanguages.push('en')
    first.audioLanguages.push('ja')
    first.sponsorBlockCategories.push('sponsor')
    first.danmakuFormats?.push('ass')
    expect(second.subtitleLanguages).toEqual([])
    expect(second.audioLanguages).toEqual([])
    expect(second.sponsorBlockCategories).toEqual([])
    expect(second.includeDanmaku).toBe(false)
    expect(second.danmakuFormats).toEqual(['xml'])
    expect(second.keepCoverSidecar).toBe(false)
    expect(second.includeNfo).toBe(false)
  })

  it('gates aria2c on the Local Engine capability without mutating other UI state', () => {
    const source = {
      ...createDefaultLocalEngineAdvancedOptions(),
      segmentStart: '01:20',
      segmentEnd: '03:45',
      splitChapters: true,
      subtitleLanguages: ['zh-Hans', 'en'],
      audioLanguages: ['zh', 'en'],
      sponsorBlockCategories: ['sponsor', 'intro'] as const,
      useAria2c: true,
      includeDanmaku: true,
      danmakuFormats: ['ass', 'json'] as LocalEngineDanmakuFormat[],
      keepCoverSidecar: true,
      includeNfo: true,
    }

    const unavailable = resolveLocalEngineAdvancedJobOptions({
      ...source,
      sponsorBlockCategories: [...source.sponsorBlockCategories],
    }, false)
    const ready = resolveLocalEngineAdvancedJobOptions({
      ...source,
      sponsorBlockCategories: [...source.sponsorBlockCategories],
    }, true)

    expect(unavailable.useAria2c).toBe(false)
    expect(ready.useAria2c).toBe(true)
    expect(ready.segmentStart).toBe('01:20')
    expect(ready.segmentEnd).toBe('03:45')
    expect(ready.splitChapters).toBe(true)
    expect(ready.subtitleLanguages).toEqual(['zh-Hans', 'en'])
    expect(ready.audioLanguages).toEqual(['zh', 'en'])
    expect(ready.sponsorBlockCategories).toEqual(['sponsor', 'intro'])
    expect(ready.includeDanmaku).toBe(true)
    expect(unavailable.includeDanmaku).toBe(true)
    expect(ready.danmakuFormats).toEqual(['ass', 'json'])
    expect(unavailable.danmakuFormats).toEqual(['ass', 'json'])
    expect(ready.danmakuFormats).not.toBe(source.danmakuFormats)
    expect(ready.keepCoverSidecar).toBe(true)
    expect(unavailable.keepCoverSidecar).toBe(true)
    expect(ready.includeNfo).toBe(true)
    expect(unavailable.includeNfo).toBe(true)
    expect(source.useAria2c).toBe(true)
    expect(source.includeDanmaku).toBe(true)
    expect(source.keepCoverSidecar).toBe(true)
    expect(source.includeNfo).toBe(true)
  })

  it('normalizes advanced media capabilities from bridge status', () => {
    const status = normalizeLocalEngineBridgeStatusPayload({
      ok: true,
      bridgeProtocol: 5,
      version: '0.15.0',
      advancedMedia: true,
      aria2Ready: true,
      batchDownloadReady: true,
    })

    expect(status?.advancedMedia).toBe(true)
    expect(status?.aria2Ready).toBe(true)
    expect(status?.batchDownloadReady).toBe(true)
  })

  it('permanently wires Batch Workbench controls into the unified batch options builder', () => {
    const source = readFileSync(
      resolve(process.cwd(), 'src/components/downloader/BatchWorkbench.tsx'),
      'utf8',
    )

    expect(source).toContain('<LocalEngineAdvancedControls')
    expect(source).toContain('options: buildLocalEngineBatchOptions(')
    expect(source).toContain('advancedOptions,')
    expect(source).toContain('Boolean(bridge?.aria2Ready)')
    expect(source).toContain('setSubmissionResult(null)')
    expect(source).toContain('setSubmissionError(\'\')')
  })

  it('keeps the shared advanced controls fail-closed for cover sidecars', () => {
    const source = readFileSync(
      resolve(process.cwd(), 'src/components/downloader/LocalEngineAdvancedControls.tsx'),
      'utf8',
    )

    expect(source).toContain("getCoverSidecarCapability")
    expect(source).toContain("coverSidecarCapability !== false || !value.keepCoverSidecar")
    expect(source).toContain("keepCoverSidecar: false")
    expect(source).toContain("disabled={disabled || !coverSidecarReady}")
    expect(source).toContain("checked={coverSidecarReady && Boolean(value.keepCoverSidecar)}")
  })
})