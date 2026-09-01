import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

import {
  DOWNLOAD_HISTORY_MAX_COUNT,
  DOWNLOAD_HISTORY_STORAGE_KEY,
  RECENT_PARSE_HISTORY_MAX_COUNT,
  RECENT_PARSE_HISTORY_STORAGE_KEY,
} from '../src/lib/constants'

describe('recent parse history semantics', () => {
  it('keeps the legacy browser storage key without claiming download completion', () => {
    expect(RECENT_PARSE_HISTORY_STORAGE_KEY).toBe('download-history')
    expect(DOWNLOAD_HISTORY_STORAGE_KEY).toBe(RECENT_PARSE_HISTORY_STORAGE_KEY)
    expect(DOWNLOAD_HISTORY_MAX_COUNT).toBe(RECENT_PARSE_HISTORY_MAX_COUNT)
  })

  it('labels parse-success records as recent parses in the visible workbench', () => {
    const source = readFileSync(
      resolve(process.cwd(), 'src/app/[locale]/download-history.tsx'),
      'utf8',
    )

    expect(source).toContain("title: '最近解析'")
    expect(source).toContain("title: 'Recent parses'")
    expect(source).toContain('does not delete downloaded files or the Local Engine download archive')
    expect(source).toContain('Parse success, not download completion')
  })
})
