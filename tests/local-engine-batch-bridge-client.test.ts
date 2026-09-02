import { describe, expect, it } from 'vitest'

import {
  normalizeLocalEngineBatchSubmissionResult,
  normalizeLocalEngineBridgeStatusPayload,
  type LocalEngineBatchSubmissionResult,
} from '../src/lib/local-engine-bridge'

describe('Local Engine batch bridge client normalization', () => {
  it('normalizes accepted and rejected row outcomes without retaining unexpected fields', () => {
    const result = normalizeLocalEngineBatchSubmissionResult({
      ok: true,
      code: 'BATCH_PARTIAL',
      format: 'txt',
      inputCount: 3,
      inputIssueCount: 1,
      attemptedCount: 2,
      acceptedCount: 1,
      rejectedCount: 1,
      startedCount: 1,
      queuedCount: 0,
      remainingCount: 1,
      stoppedCode: 'QUEUE_FULL',
      issues: [
        {
          row: 2,
          code: 'INVALID_URL',
          message: ' Invalid   URL ',
          sourceUrl: 'https://example.com/private?token=must-not-surface',
        },
      ],
      outcomes: [
        {
          row: 1,
          accepted: true,
          status: 202,
          code: 'ACCEPTED',
          sourceUrl: 'https://example.com/private?token=must-not-surface',
        },
        {
          row: 3,
          accepted: false,
          status: 409,
          code: 'QUEUE_FULL',
        },
      ],
    }, 202)

    expect(result).toEqual<LocalEngineBatchSubmissionResult>({
      ok: true,
      httpStatus: 202,
      code: 'BATCH_PARTIAL',
      format: 'txt',
      inputCount: 3,
      inputIssueCount: 1,
      attemptedCount: 2,
      acceptedCount: 1,
      rejectedCount: 1,
      startedCount: 1,
      queuedCount: 0,
      remainingCount: 1,
      stoppedCode: 'QUEUE_FULL',
      issues: [{ row: 2, code: 'INVALID_URL', message: 'Invalid URL' }],
      outcomes: [
        { row: 1, accepted: true, status: 202, code: 'ACCEPTED' },
        { row: 3, accepted: false, status: 409, code: 'QUEUE_FULL' },
      ],
    })
    expect(JSON.stringify(result)).not.toContain('must-not-surface')
    expect(JSON.stringify(result)).not.toContain('sourceUrl')
  })

  it('accepts complete rejected/stopped batch payloads so UI can render row detail', () => {
    const rejected = normalizeLocalEngineBatchSubmissionResult({
      ok: false,
      code: 'BATCH_REJECTED',
      format: 'csv',
      inputCount: 1,
      inputIssueCount: 0,
      attemptedCount: 1,
      acceptedCount: 0,
      rejectedCount: 1,
      startedCount: 0,
      queuedCount: 0,
      remainingCount: 0,
      stoppedCode: null,
      issues: [],
      outcomes: [{ row: 2, accepted: false, status: 400, code: 'BAD_REQUEST' }],
    }, 400)
    expect(rejected?.ok).toBe(false)
    expect(rejected?.httpStatus).toBe(400)
    expect(rejected?.code).toBe('BATCH_REJECTED')
    expect(rejected?.outcomes[0].code).toBe('BAD_REQUEST')

    const stopped = normalizeLocalEngineBatchSubmissionResult({
      ok: false,
      code: 'BATCH_STOPPED',
      format: 'txt',
      inputCount: 2,
      inputIssueCount: 0,
      attemptedCount: 1,
      acceptedCount: 0,
      rejectedCount: 1,
      startedCount: 0,
      queuedCount: 0,
      remainingCount: 1,
      stoppedCode: 'QUEUE_FULL',
      issues: [],
      outcomes: [{ row: 1, accepted: false, status: 409, code: 'QUEUE_FULL' }],
    }, 409)
    expect(stopped?.code).toBe('BATCH_STOPPED')
    expect(stopped?.stoppedCode).toBe('QUEUE_FULL')
    expect(stopped?.remainingCount).toBe(1)
  })

  it('rejects malformed batch payloads rather than inventing counts', () => {
    expect(normalizeLocalEngineBatchSubmissionResult(null, 202)).toBeNull()
    expect(normalizeLocalEngineBatchSubmissionResult({ ok: true, code: 'BATCH_ACCEPTED' }, 202)).toBeNull()
    expect(normalizeLocalEngineBatchSubmissionResult({
      ok: true,
      code: 'BATCH_ACCEPTED',
      format: 'xml',
      inputCount: 1,
      inputIssueCount: 0,
      attemptedCount: 1,
      acceptedCount: 1,
      rejectedCount: 0,
      startedCount: 1,
      queuedCount: 0,
      remainingCount: 0,
      stoppedCode: null,
      issues: [],
      outcomes: [],
    }, 202)).toBeNull()
  })

  it('normalizes batch capability independently from protocol v5', () => {
    const oldV5 = normalizeLocalEngineBridgeStatusPayload({
      ok: true,
      bridgeProtocol: 5,
      version: '0.15.0',
    })
    expect(oldV5?.bridgeProtocol).toBe(5)
    expect(oldV5?.batchDownloadReady).toBe(false)

    const batchCapableV5 = normalizeLocalEngineBridgeStatusPayload({
      ok: true,
      bridgeProtocol: 5,
      version: '0.15.0',
      batchDownloadReady: true,
    })
    expect(batchCapableV5?.batchDownloadReady).toBe(true)
  })
})
