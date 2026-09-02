export const BATCH_WORKBENCH_MAX_INPUT_CHARS = 1_000_000
export const BATCH_WORKBENCH_MAX_ROWS = 2_000
export const BATCH_WORKBENCH_MAX_ITEMS = 500
export const BATCH_WORKBENCH_MAX_FILE_BYTES = 4_200_000

export type BatchWorkbenchFormat = 'auto' | 'txt' | 'csv'
export type BatchWorkbenchResolvedFormat = 'txt' | 'csv'

const URL_HEADERS = new Set([
  'url',
  'sourceurl',
  'source_url',
  'link',
  '网址',
  '链接',
])

export interface BatchWorkbenchPreview {
  resolvedFormat: BatchWorkbenchResolvedFormat
  totalRows: number
  meaningfulRows: number
  estimatedItems: number
  ignoredRows: number
  headerRow: number | null
  overCharacterLimit: boolean
  overRowLimit: boolean
  overItemLimit: boolean
}

function parseCsvCells(line: string): string[] {
  const cells: string[] = []
  let value = ''
  let quoted = false

  for (let index = 0; index < line.length; index += 1) {
    const character = line[index]
    if (character === '"') {
      if (quoted && line[index + 1] === '"') {
        value += '"'
        index += 1
      } else {
        quoted = !quoted
      }
      continue
    }
    if (character === ',' && !quoted) {
      cells.push(value.trim())
      value = ''
      continue
    }
    value += character
  }
  cells.push(value.trim())
  return cells
}

function firstMeaningfulRow(lines: string[]): { index: number; text: string } | null {
  for (let index = 0; index < lines.length; index += 1) {
    const text = lines[index].trim()
    if (!text || text.startsWith('#')) continue
    return { index, text }
  }
  return null
}

export function detectBatchWorkbenchFormat(input: string): BatchWorkbenchResolvedFormat {
  const normalized = input.replace(/^\uFEFF/, '')
  const first = firstMeaningfulRow(normalized.split(/\r?\n/))
  if (!first) return 'txt'

  const headers = parseCsvCells(first.text).map((cell) => cell.toLowerCase().replace(/[\s-]+/g, ''))
  return headers.some((header) => URL_HEADERS.has(header)) ? 'csv' : 'txt'
}

export function buildBatchWorkbenchPreview(
  input: string,
  format: BatchWorkbenchFormat = 'auto',
): BatchWorkbenchPreview {
  const normalized = input.replace(/^\uFEFF/, '')
  const lines = normalized ? normalized.split(/\r?\n/) : []
  const resolvedFormat: BatchWorkbenchResolvedFormat = format === 'auto'
    ? detectBatchWorkbenchFormat(normalized)
    : format

  let meaningfulRows = 0
  let ignoredRows = 0
  let headerRow: number | null = null

  for (let index = 0; index < lines.length; index += 1) {
    const text = lines[index].trim()
    if (!text || text.startsWith('#')) {
      ignoredRows += 1
      continue
    }
    meaningfulRows += 1
    if (resolvedFormat === 'csv' && headerRow === null) {
      headerRow = index + 1
    }
  }

  const estimatedItems = Math.max(0, meaningfulRows - (resolvedFormat === 'csv' && headerRow !== null ? 1 : 0))

  return {
    resolvedFormat,
    totalRows: lines.length,
    meaningfulRows,
    estimatedItems,
    ignoredRows,
    headerRow,
    overCharacterLimit: normalized.length > BATCH_WORKBENCH_MAX_INPUT_CHARS,
    overRowLimit: lines.length > BATCH_WORKBENCH_MAX_ROWS,
    overItemLimit: estimatedItems > BATCH_WORKBENCH_MAX_ITEMS,
  }
}

export function batchWorkbenchCanContinue(preview: BatchWorkbenchPreview): boolean {
  return preview.estimatedItems > 0
    && !preview.overCharacterLimit
    && !preview.overRowLimit
    && !preview.overItemLimit
}
