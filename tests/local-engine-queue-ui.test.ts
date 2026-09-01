import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('Local Engine queue workbench', () => {
  const source = readFileSync(
    resolve(process.cwd(), 'src/components/downloader/LocalEngineDownloadCard.tsx'),
    'utf8',
  )

  it('sends a display title and renders server-sanitized queue summaries', () => {
    expect(source).toContain("displayTitle: typeof result.title === 'string' ? result.title : undefined")
    expect(source).toContain('const queuedJobs = bridge?.queuedJobs || []')
    expect(source).toContain('{queuedJob.label}')
    expect(source).toContain('{queuedJob.sourceHost}')
    expect(source).not.toContain('{queuedJob.sourceUrl}')
  })

  it('allows one waiting job to be cancelled without conflating it with the active cancel action', () => {
    expect(source).toContain('cancelLocalEngineQueuedJob')
    expect(source).toContain('handleCancelQueued')
    expect(source).toContain("await cancelLocalEngineQueuedJob(jobId)")
    expect(source).toContain("await cancelLocalEngineBridgeJob()")
    expect(source).toContain("error.code === 'QUEUE_ITEM_NOT_FOUND'")
  })

  it('keeps the queue presentation flat and compact', () => {
    expect(source).toContain('className="mt-3 border-y" aria-label={copy.queueJobs}')
    expect(source).toContain('className="divide-y border-t"')
    expect(source).not.toContain('rounded-xl')
  })
})
