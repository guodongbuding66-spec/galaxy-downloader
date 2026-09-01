import { describe, expect, it } from 'vitest'

import {
  LocalEngineBridgeSubmissionError,
  localizeLocalEngineSubmissionMessage,
  normalizeLocalEngineQueuedJobs,
} from '../src/lib/local-engine-bridge'

describe('Local Engine bridge submission errors', () => {
  it('localizes stable queue and lifecycle codes', () => {
    expect(localizeLocalEngineSubmissionMessage('QUEUE_FULL', 'fallback', 'zh-CN'))
      .toContain('队列已满')
    expect(localizeLocalEngineSubmissionMessage('ENGINE_SHUTTING_DOWN', 'fallback', 'zh-TW'))
      .toContain('正在結束')
    expect(localizeLocalEngineSubmissionMessage('ENGINE_HANDOFF_TIMEOUT', 'fallback', 'ja-JP'))
      .toContain('タイムアウト')
    expect(localizeLocalEngineSubmissionMessage('ENGINE_BUSY', 'fallback', 'es-ES'))
      .toContain('otra tarea')
    expect(localizeLocalEngineSubmissionMessage('QUEUE_FULL', 'fallback', 'ru-RU'))
      .toContain('очередь')
  })

  it('keeps backend detail for unknown and validation codes', () => {
    expect(localizeLocalEngineSubmissionMessage('BAD_REQUEST', 'Invalid media URL', 'en-US'))
      .toBe('Invalid media URL')
    expect(localizeLocalEngineSubmissionMessage('SOMETHING_NEW', 'future detail', 'en-US'))
      .toBe('future detail')
  })

  it('preserves code and HTTP status on the typed error', () => {
    const error = new LocalEngineBridgeSubmissionError('Queue full', 'QUEUE_FULL', 409)
    expect(error.name).toBe('LocalEngineBridgeSubmissionError')
    expect(error.message).toBe('Queue full')
    expect(error.code).toBe('QUEUE_FULL')
    expect(error.status).toBe(409)
  })
})

describe('Local Engine visible queue normalization', () => {
  it('keeps only safe ids and summaries, deduplicates ids, and sorts positions', () => {
    const jobs = normalizeLocalEngineQueuedJobs([
      {
        id: 'b'.repeat(32),
        position: 2,
        label: '  Second   video  ',
        sourceHost: 'media.example.com',
        sourceUrl: 'https://media.example.com/watch?token=must-not-surface',
      },
      {
        id: 'a'.repeat(32),
        position: 1,
        label: 'First\nvideo',
        sourceHost: 'example.com',
      },
      {
        id: 'a'.repeat(32),
        position: 3,
        label: 'Duplicate',
        sourceHost: 'duplicate.example',
      },
      {
        id: '../../bad',
        position: 4,
        label: 'Invalid id',
        sourceHost: 'invalid.example',
      },
    ])

    expect(jobs).toEqual([
      {
        id: 'a'.repeat(32),
        position: 1,
        label: 'First video',
        sourceHost: 'example.com',
      },
      {
        id: 'b'.repeat(32),
        position: 2,
        label: 'Second video',
        sourceHost: 'media.example.com',
      },
    ])
    expect(JSON.stringify(jobs)).not.toContain('must-not-surface')
    expect(JSON.stringify(jobs)).not.toContain('sourceUrl')
  })

  it('falls back to hostname, truncates visible text, and caps the queue list', () => {
    const raw = Array.from({ length: 40 }, (_, index) => ({
      id: index.toString(16).padStart(32, '0'),
      position: index + 1,
      label: index === 0 ? '' : `Job ${index}`,
      sourceHost: index === 0 ? `${'x'.repeat(180)}.example.com` : 'example.com',
    }))

    const jobs = normalizeLocalEngineQueuedJobs(raw)
    expect(jobs).toHaveLength(25)
    expect(jobs[0].label).toBe(jobs[0].sourceHost)
    expect(jobs[0].sourceHost.length).toBeLessThanOrEqual(120)
    expect(jobs.at(-1)?.position).toBe(25)
  })
})
