import { describe, expect, it } from 'vitest'

import {
  LocalEngineBridgeSubmissionError,
  localizeLocalEngineSubmissionMessage,
  normalizeLocalEngineQueuedJobs,
  normalizeLocalEngineResumeJobs,
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
    expect(localizeLocalEngineSubmissionMessage('RESUME_JOB_NOT_FOUND', 'fallback', 'zh-CN'))
      .toContain('可恢复任务')
    expect(localizeLocalEngineSubmissionMessage('NO_PAUSABLE_JOB', 'fallback', 'en-US'))
      .toContain('can be paused')
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

describe('Local Engine recoverable job normalization', () => {
  it('keeps only privacy-safe resumable summaries and fails unknown modes closed to restart', () => {
    const jobs = normalizeLocalEngineResumeJobs([
      {
        id: 'a'.repeat(32),
        state: 'paused',
        sourceHost: 'media.example.com',
        label: '  Demo   download ',
        videoQuality: '1080p',
        progress: 42.75,
        downloaded: '512 MiB',
        resumeMode: 'continue',
        sourceUrl: 'https://media.example.com/watch?token=secret',
        payload: { cookie: 'must-not-surface' },
      },
      {
        id: 'b'.repeat(32),
        state: 'interrupted',
        sourceHost: 'channels.weixin.qq.com',
        label: 'WeChat video',
        progress: 130,
        resumeMode: 'future-mode',
      },
      {
        id: '../../bad',
        state: 'paused',
        sourceHost: 'bad.example',
      },
      {
        id: 'c'.repeat(32),
        state: 'running',
        sourceHost: 'hidden.example',
      },
    ])

    expect(jobs).toEqual([
      {
        id: 'a'.repeat(32),
        state: 'paused',
        createdAt: '',
        updatedAt: '',
        sourceHost: 'media.example.com',
        label: 'Demo download',
        videoQuality: '1080p',
        progress: 42.75,
        downloaded: '512 MiB',
        resumeMode: 'continue',
      },
      {
        id: 'b'.repeat(32),
        state: 'interrupted',
        createdAt: '',
        updatedAt: '',
        sourceHost: 'channels.weixin.qq.com',
        label: 'WeChat video',
        videoQuality: 'best',
        progress: 100,
        downloaded: '—',
        resumeMode: 'restart',
      },
    ])
    const rendered = JSON.stringify(jobs)
    expect(rendered).not.toContain('secret')
    expect(rendered).not.toContain('cookie')
    expect(rendered).not.toContain('sourceUrl')
    expect(rendered).not.toContain('payload')
  })

  it('deduplicates ids and caps the visible recovery list', () => {
    const raw = Array.from({ length: 40 }, (_, index) => ({
      id: index.toString(16).padStart(32, '0'),
      state: index % 2 === 0 ? 'paused' : 'interrupted',
      sourceHost: 'example.com',
      label: `Job ${index}`,
      progress: index,
      resumeMode: 'continue',
    }))
    raw.splice(1, 0, { ...raw[0], label: 'duplicate' })
    const jobs = normalizeLocalEngineResumeJobs(raw)
    expect(jobs).toHaveLength(24)
    expect(new Set(jobs.map((job) => job.id)).size).toBe(jobs.length)
  })
})

