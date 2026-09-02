import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

import {
  createDefaultLocalEngineAdvancedOptions,
  resolveLocalEngineAdvancedJobOptions,
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
    })

    first.subtitleLanguages.push('en')
    first.audioLanguages.push('ja')
    first.sponsorBlockCategories.push('sponsor')
    expect(second.subtitleLanguages).toEqual([])
    expect(second.audioLanguages).toEqual([])
    expect(second.sponsorBlockCategories).toEqual([])
  })

  it('gates aria2c on the Local Engine capability without mutating UI state', () => {
    const source = {
      ...createDefaultLocalEngineAdvancedOptions(),
      segmentStart: '01:20',
      segmentEnd: '03:45',
      splitChapters: true,
      subtitleLanguages: ['zh-Hans', 'en'],
      audioLanguages: ['zh', 'en'],
      sponsorBlockCategories: ['sponsor', 'intro'] as const,
      useAria2c: true,
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
    expect(source.useAria2c).toBe(true)
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
})
