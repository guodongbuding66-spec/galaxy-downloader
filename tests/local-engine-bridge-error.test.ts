import { describe, expect, it } from 'vitest'

import {
  LocalEngineBridgeSubmissionError,
  localizeLocalEngineSubmissionMessage,
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
