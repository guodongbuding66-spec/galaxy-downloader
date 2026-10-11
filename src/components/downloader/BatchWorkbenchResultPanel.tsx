'use client'

import { useMemo } from 'react'
import { usePathname } from 'next/navigation'
import { AlertTriangle, CheckCircle2 } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import type { LocalEngineBatchSubmissionResult } from '@/lib/local-engine-bridge'
import { cn } from '@/lib/utils'

type FeedbackRow = {
  row: number
  code: string
  message: string
}

const MAX_VISIBLE_FEEDBACK_ROWS = 80

export function buildBatchWorkbenchFeedback(
  result: LocalEngineBatchSubmissionResult,
): { rows: FeedbackRow[]; total: number } {
  const seen = new Set<string>()
  const feedback: FeedbackRow[] = []

  for (const issue of result.issues) {
    const key = `${issue.row}:${issue.code}`
    if (seen.has(key)) continue
    seen.add(key)
    feedback.push({ row: issue.row, code: issue.code, message: issue.message })
  }

  for (const outcome of result.outcomes) {
    if (outcome.accepted) continue
    const key = `${outcome.row}:${outcome.code}`
    if (seen.has(key)) continue
    seen.add(key)
    feedback.push({ row: outcome.row, code: outcome.code, message: '' })
  }

  feedback.sort((left, right) => left.row - right.row || left.code.localeCompare(right.code))
  return { rows: feedback.slice(0, MAX_VISIBLE_FEEDBACK_ROWS), total: feedback.length }
}

type Copy = {
  accepted: string
  partial: string
  rejected: string
  stopped: string
  acceptedCount: string
  startedCount: string
  queuedCount: string
  rejectedCount: string
  remainingCount: string
  inputIssues: string
  rowIssues: string
  row: string
  hiddenIssues: string
  stoppedCode: string
}

const COPY: Record<string, Copy> = {
  zh: {
    accepted: '批量任务已接收', partial: '部分任务已接收', rejected: '批量任务未接收', stopped: '批量提交已停止', acceptedCount: '已接收', startedCount: '已开始', queuedCount: '已排队', rejectedCount: '被拒绝', remainingCount: '未尝试', inputIssues: '输入问题', rowIssues: '逐行问题', row: '第 {row} 行', hiddenIssues: '另有 {count} 条问题未展开', stoppedCode: '停止原因：{code}',
  },
  'zh-tw': {
    accepted: '批次工作已接收', partial: '部分工作已接收', rejected: '批次工作未接收', stopped: '批次提交已停止', acceptedCount: '已接收', startedCount: '已開始', queuedCount: '已排隊', rejectedCount: '被拒絕', remainingCount: '未嘗試', inputIssues: '輸入問題', rowIssues: '逐行問題', row: '第 {row} 行', hiddenIssues: '另有 {count} 條問題未展開', stoppedCode: '停止原因：{code}',
  },
  en: {
    accepted: 'Batch accepted', partial: 'Batch partially accepted', rejected: 'Batch rejected', stopped: 'Batch submission stopped', acceptedCount: 'Accepted', startedCount: 'Started', queuedCount: 'Queued', rejectedCount: 'Rejected', remainingCount: 'Not attempted', inputIssues: 'Input issues', rowIssues: 'Per-row issues', row: 'Row {row}', hiddenIssues: '{count} more issues are not expanded', stoppedCode: 'Stopped: {code}',
  },
  ja: {
    accepted: '一括ジョブを受け付けました', partial: '一部のジョブを受け付けました', rejected: '一括ジョブは受け付けられませんでした', stopped: '一括送信を停止しました', acceptedCount: '受付済み', startedCount: '開始', queuedCount: '待機中', rejectedCount: '拒否', remainingCount: '未試行', inputIssues: '入力の問題', rowIssues: '行ごとの問題', row: '{row} 行目', hiddenIssues: 'ほか {count} 件の問題は省略されています', stoppedCode: '停止理由：{code}',
  },
  es: {
    accepted: 'Lote aceptado', partial: 'Lote aceptado parcialmente', rejected: 'Lote rechazado', stopped: 'Envío del lote detenido', acceptedCount: 'Aceptadas', startedCount: 'Iniciadas', queuedCount: 'En cola', rejectedCount: 'Rechazadas', remainingCount: 'Sin intentar', inputIssues: 'Problemas de entrada', rowIssues: 'Problemas por fila', row: 'Fila {row}', hiddenIssues: 'Hay {count} problemas más sin mostrar', stoppedCode: 'Detenido: {code}',
  },
  ru: {
    accepted: 'Пакет принят', partial: 'Пакет принят частично', rejected: 'Пакет отклонён', stopped: 'Пакетная отправка остановлена', acceptedCount: 'Принято', startedCount: 'Запущено', queuedCount: 'В очереди', rejectedCount: 'Отклонено', remainingCount: 'Не проверено', inputIssues: 'Проблемы ввода', rowIssues: 'Проблемы по строкам', row: 'Строка {row}', hiddenIssues: 'Ещё проблем: {count}', stoppedCode: 'Остановлено: {code}',
  },
}

function copyFor(pathname: string | null): Copy {
  const locale = pathname?.split('/').filter(Boolean)[0] || 'en'
  return COPY[locale] || COPY.en
}

function statusTitle(result: LocalEngineBatchSubmissionResult, copy: Copy): string {
  if (result.code === 'BATCH_ACCEPTED') return copy.accepted
  if (result.code === 'BATCH_PARTIAL') return copy.partial
  if (result.code === 'BATCH_STOPPED') return copy.stopped
  return copy.rejected
}

function statusVisual(result: LocalEngineBatchSubmissionResult): {
  badge: 'success' | 'warning' | 'destructive'
  icon: string
} {
  if (result.code === 'BATCH_ACCEPTED') {
    return { badge: 'success', icon: 'text-[hsl(var(--success))]' }
  }
  if (result.code === 'BATCH_PARTIAL' || result.code === 'BATCH_STOPPED') {
    return { badge: 'warning', icon: 'text-[hsl(var(--warning))]' }
  }
  return { badge: 'destructive', icon: 'text-destructive' }
}

export function BatchWorkbenchResultPanel({ result }: { result: LocalEngineBatchSubmissionResult | null }) {
  const pathname = usePathname()
  const copy = copyFor(pathname)
  const feedback = useMemo(() => result ? buildBatchWorkbenchFeedback(result) : null, [result])
  if (!result || !feedback) return null

  const successful = result.acceptedCount > 0
  const visual = statusVisual(result)
  const metrics = [
    [copy.acceptedCount, result.acceptedCount],
    [copy.startedCount, result.startedCount],
    [copy.queuedCount, result.queuedCount],
    [copy.rejectedCount, result.rejectedCount],
    [copy.remainingCount, result.remainingCount],
    [copy.inputIssues, result.inputIssueCount],
  ] as const

  return (
    <div className="mt-3 border-t pt-3" aria-live="polite">
      <div className="surface-subtle flex items-start gap-2.5 rounded-md border px-3 py-2.5">
        {successful ? (
          <CheckCircle2 className={cn('mt-0.5 h-4 w-4 shrink-0', visual.icon)} aria-hidden="true" />
        ) : (
          <AlertTriangle className={cn('mt-0.5 h-4 w-4 shrink-0', visual.icon)} aria-hidden="true" />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold leading-5">{statusTitle(result, copy)}</span>
            <Badge variant={visual.badge}>{result.code}</Badge>
            <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{result.format}</span>
          </div>
          {result.stoppedCode ? (
            <div className="mt-1 text-[11px] leading-4 text-muted-foreground">
              {copy.stoppedCode.replace('{code}', result.stoppedCode)}
            </div>
          ) : null}
        </div>
      </div>

      <div className="mt-2 grid grid-cols-2 gap-px overflow-hidden border-y bg-border sm:grid-cols-3 lg:grid-cols-6">
        {metrics.map(([label, value]) => (
          <div key={label} className="min-w-0 bg-background px-2.5 py-2">
            <div className="text-[11px] leading-4 text-muted-foreground">{label}</div>
            <div className="mt-0.5 text-base font-semibold tabular-nums tracking-tight">{value}</div>
          </div>
        ))}
      </div>

      {feedback.total > 0 ? (
        <div className="mt-3">
          <div className="mb-1.5 flex items-center justify-between gap-2 text-xs font-semibold">
            <span>{copy.rowIssues}</span>
            <span className="tabular-nums text-muted-foreground">{feedback.total}</span>
          </div>
          <div className="max-h-56 divide-y overflow-y-auto border-y">
            {feedback.rows.map((item) => (
              <div key={`${item.row}-${item.code}`} className="grid min-h-10 grid-cols-[84px_minmax(0,1fr)] gap-3 px-2 py-2 text-xs">
                <span className="tabular-nums leading-5 text-muted-foreground">{copy.row.replace('{row}', String(item.row))}</span>
                <div className="min-w-0 leading-5">
                  <span className="font-semibold">{item.code}</span>
                  {item.message ? <span className="ms-2 text-muted-foreground">{item.message}</span> : null}
                </div>
              </div>
            ))}
          </div>
          {feedback.total > feedback.rows.length ? (
            <div className="mt-1.5 text-[11px] leading-4 text-muted-foreground">
              {copy.hiddenIssues.replace('{count}', String(feedback.total - feedback.rows.length))}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
