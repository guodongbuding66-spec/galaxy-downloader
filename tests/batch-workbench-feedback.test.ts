import { describe, expect, it } from 'vitest'

import { buildBatchWorkbenchFeedback } from '../src/components/downloader/BatchWorkbenchResultPanel'
import type { LocalEngineBatchSubmissionResult } from '../src/lib/local-engine-bridge'

function result(overrides: Partial<LocalEngineBatchSubmissionResult> = {}): LocalEngineBatchSubmissionResult {
  return {
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
      { row: 3, accepted: false, status: 400, code: 'BAD_REQUEST' },
    ],
    ...overrides,
  }
}

describe('Batch Workbench row feedback', () => {
  it('combines parser issues with rejected submission outcomes and hides accepted rows', () => {
    expect(buildBatchWorkbenchFeedback(result())).toEqual({
      total: 2,
      rows: [
        { row: 2, code: 'INVALID_URL', message: 'Invalid URL' },
        { row: 3, code: 'BAD_REQUEST', message: '' },
      ],
    })
  })

  it('deduplicates matching row/code feedback', () => {
    const feedback = buildBatchWorkbenchFeedback(result({
      issues: [{ row: 3, code: 'BAD_REQUEST', message: 'Rejected by final validation' }],
      outcomes: [{ row: 3, accepted: false, status: 400, code: 'BAD_REQUEST' }],
    }))
    expect(feedback).toEqual({
      total: 1,
      rows: [{ row: 3, code: 'BAD_REQUEST', message: 'Rejected by final validation' }],
    })
  })

  it('caps rendered feedback without losing the total count', () => {
    const issues = Array.from({ length: 120 }, (_, index) => ({
      row: index + 1,
      code: 'INVALID_URL',
      message: 'Invalid URL',
    }))
    const feedback = buildBatchWorkbenchFeedback(result({ issues, outcomes: [] }))
    expect(feedback.total).toBe(120)
    expect(feedback.rows).toHaveLength(80)
    expect(feedback.rows[0].row).toBe(1)
    expect(feedback.rows.at(-1)?.row).toBe(80)
  })
})
