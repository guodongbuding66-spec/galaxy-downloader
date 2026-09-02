import { describe, expect, it } from 'vitest'

import {
  BATCH_WORKBENCH_MAX_INPUT_CHARS,
  BATCH_WORKBENCH_MAX_ITEMS,
  BATCH_WORKBENCH_MAX_ROWS,
  batchWorkbenchCanContinue,
  buildBatchWorkbenchPreview,
  detectBatchWorkbenchFormat,
} from '../src/components/downloader/batch-workbench-model'

describe('Batch Workbench preview model', () => {
  it('detects plain text, ignores blanks/comments, and preserves duplicate candidates in counts', () => {
    const input = [
      '# note',
      'https://example.com/a',
      '',
      'https://example.com/a',
      'https://example.com/b',
    ].join('\n')

    expect(detectBatchWorkbenchFormat(input)).toBe('txt')
    expect(buildBatchWorkbenchPreview(input, 'auto')).toMatchObject({
      resolvedFormat: 'txt',
      totalRows: 5,
      meaningfulRows: 3,
      estimatedItems: 3,
      ignoredRows: 2,
      headerRow: null,
    })
  })

  it('detects CSV URL headers including BOM and Chinese headers', () => {
    expect(detectBatchWorkbenchFormat('\uFEFFurl,title\nhttps://example.com/a,Demo')).toBe('csv')
    expect(detectBatchWorkbenchFormat('链接,标题\nhttps://example.com/a,示例')).toBe('csv')
    expect(detectBatchWorkbenchFormat('sourceUrl,name\nhttps://example.com/a,Demo')).toBe('csv')
  })

  it('treats the first meaningful CSV row as the header for estimated items', () => {
    const preview = buildBatchWorkbenchPreview(
      '# exported list\nurl,title\nhttps://example.com/a,A\nhttps://example.com/b,B',
      'auto',
    )

    expect(preview).toMatchObject({
      resolvedFormat: 'csv',
      totalRows: 4,
      meaningfulRows: 3,
      estimatedItems: 2,
      ignoredRows: 1,
      headerRow: 2,
    })
    expect(batchWorkbenchCanContinue(preview)).toBe(true)
  })

  it('honors an explicit format instead of auto detection', () => {
    expect(buildBatchWorkbenchPreview('url,title\nhttps://example.com/a,A', 'txt')).toMatchObject({
      resolvedFormat: 'txt',
      estimatedItems: 2,
      headerRow: null,
    })
  })

  it('fails the continue gate when canonical input bounds are exceeded', () => {
    const characterLimited = buildBatchWorkbenchPreview(`https://example.com/a\n${'x'.repeat(BATCH_WORKBENCH_MAX_INPUT_CHARS)}`)
    expect(characterLimited.overCharacterLimit).toBe(true)
    expect(batchWorkbenchCanContinue(characterLimited)).toBe(false)

    const rowLimited = buildBatchWorkbenchPreview(
      Array.from({ length: BATCH_WORKBENCH_MAX_ROWS + 1 }, () => '# ignored').join('\n'),
    )
    expect(rowLimited.overRowLimit).toBe(true)
    expect(batchWorkbenchCanContinue(rowLimited)).toBe(false)

    const itemLimited = buildBatchWorkbenchPreview(
      Array.from({ length: BATCH_WORKBENCH_MAX_ITEMS + 1 }, (_, index) => `https://example.com/${index}`).join('\n'),
    )
    expect(itemLimited.overItemLimit).toBe(true)
    expect(batchWorkbenchCanContinue(itemLimited)).toBe(false)
  })

  it('does not consider comments-only input actionable', () => {
    const preview = buildBatchWorkbenchPreview('# one\n\n# two')
    expect(preview.estimatedItems).toBe(0)
    expect(batchWorkbenchCanContinue(preview)).toBe(false)
  })
})
