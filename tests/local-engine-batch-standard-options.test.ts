import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

import { createDefaultLocalEngineAdvancedOptions } from '../src/lib/local-engine'
import {
  buildLocalEngineBatchOptions,
  createDefaultLocalEngineBatchPlanOptions,
} from '../src/lib/local-engine-batch-options'

describe('Batch standard Local Engine download options', () => {
  it('matches the safe single-download defaults', () => {
    expect(createDefaultLocalEngineBatchPlanOptions()).toEqual({
      videoQuality: 'best',
      audioQuality: 'best',
      includeAudio: true,
      includeSubtitle: false,
      includeCover: false,
      skipPreviouslyDownloaded: false,
    })
  })

  it('merges the standard plan with shared advanced options', () => {
    const plan = {
      ...createDefaultLocalEngineBatchPlanOptions(),
      videoQuality: '1080',
      audioQuality: '192',
      includeSubtitle: true,
      includeCover: true,
      skipPreviouslyDownloaded: true,
    }
    const advanced = {
      ...createDefaultLocalEngineAdvancedOptions(),
      splitChapters: true,
      subtitleLanguages: ['zh-Hans', 'en'],
      sponsorBlockCategories: ['sponsor'] as const,
      useAria2c: true,
    }

    const options = buildLocalEngineBatchOptions(
      plan,
      { ...advanced, sponsorBlockCategories: [...advanced.sponsorBlockCategories] },
      false,
    )

    expect(options).toMatchObject({
      videoQuality: '1080',
      audioQuality: '192',
      includeAudio: true,
      includeSubtitle: true,
      subtitleLanguage: null,
      includeCover: true,
      skipPreviouslyDownloaded: true,
      splitChapters: true,
      subtitleLanguages: ['zh-Hans', 'en'],
      sponsorBlockCategories: ['sponsor'],
      useAria2c: false,
    })
  })

  it('keeps Download Archive opt-in even when duplicate batch rows are allowed', () => {
    const defaults = buildLocalEngineBatchOptions(
      createDefaultLocalEngineBatchPlanOptions(),
      createDefaultLocalEngineAdvancedOptions(),
      true,
    )
    expect(defaults.skipPreviouslyDownloaded).toBe(false)
  })

  it('permanently wires plan state and controls into Batch Workbench submission', () => {
    const source = readFileSync(
      resolve(process.cwd(), 'src/components/downloader/BatchWorkbench.tsx'),
      'utf8',
    )
    expect(source).toContain('<BatchDownloadPlanControls')
    expect(source).toContain('createDefaultLocalEngineBatchPlanOptions()')
    expect(source).toContain('options: buildLocalEngineBatchOptions(')
    expect(source).toContain('planOptions,')
  })
})
