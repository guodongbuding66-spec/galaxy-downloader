'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { usePathname } from 'next/navigation'
import {
  CheckCircle2,
  ChevronDown,
  ClipboardPaste,
  FileUp,
  ListChecks,
  Loader2,
  RotateCw,
  Send,
  X,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { toast } from '@/lib/deferred-toast'
import { createDefaultLocalEngineAdvancedOptions } from '@/lib/local-engine'
import {
  buildLocalEngineBatchOptions,
  createDefaultLocalEngineBatchPlanOptions,
} from '@/lib/local-engine-batch-options'
import {
  getLocalEngineBridgeStatus,
  submitLocalEngineBatchInput,
  type LocalEngineBatchSubmissionResult,
  type LocalEngineBridgeStatus,
} from '@/lib/local-engine-bridge'

import { BatchDownloadPlanControls } from './BatchDownloadPlanControls'
import { LocalEngineAdvancedControls } from './LocalEngineAdvancedControls'
import { BatchWorkbenchResultPanel } from './BatchWorkbenchResultPanel'

import {
  BATCH_WORKBENCH_MAX_FILE_BYTES,
  BATCH_WORKBENCH_MAX_INPUT_CHARS,
  BATCH_WORKBENCH_MAX_ITEMS,
  BATCH_WORKBENCH_MAX_ROWS,
  batchWorkbenchCanContinue,
  buildBatchWorkbenchPreview,
  type BatchWorkbenchFormat,
} from './batch-workbench-model'

type BatchCopy = {
  title: string
  description: string
  beta: string
  ready: string
  unsupported: string
  offline: string
  checking: string
  inputLabel: string
  placeholder: string
  paste: string
  importFile: string
  clear: string
  format: string
  auto: string
  txt: string
  csv: string
  detected: string
  estimated: string
  rows: string
  ignored: string
  queue: string
  limits: string
  tooManyChars: string
  tooManyRows: string
  tooManyItems: string
  fileTooLarge: string
  fileReadFailed: string
  imported: string
  previewNote: string
  previewReady: string
  nextStage: string
  refresh: string
}

const COPY: Record<string, BatchCopy> = {
  zh: {
    title: '批量下载工作台',
    description: '粘贴多条链接，或导入 TXT / CSV。当前先核对格式、数量与本地引擎能力。',
    beta: '批量',
    ready: '本地引擎已支持批量',
    unsupported: '当前本地引擎需要升级后才能批量下载',
    offline: '本地引擎未连接',
    checking: '正在检查本地引擎',
    inputLabel: '批量链接或 CSV 内容',
    placeholder: 'TXT：每行一个链接\n\nCSV：url,title\nhttps://example.com/video,标题',
    paste: '粘贴',
    importFile: '导入 TXT / CSV',
    clear: '清空',
    format: '输入格式',
    auto: '自动识别',
    txt: 'TXT / 每行一个链接',
    csv: 'CSV',
    detected: '识别为 {format}',
    estimated: '预计 {count} 项',
    rows: '{count} 行',
    ignored: '忽略 {count} 行空白/注释',
    queue: '当前队列 {count}/{capacity}',
    limits: '上限：100 万字符 · 2000 行 · 500 项',
    tooManyChars: '输入超过 100 万字符上限',
    tooManyRows: '输入超过 2000 行上限',
    tooManyItems: '预计项目超过 500 项上限',
    fileTooLarge: '文件过大，不能作为批量输入读取',
    fileReadFailed: '无法读取这个文件',
    imported: '已导入 {name}',
    previewNote: '这里是快速预估，不替代 Local Engine 最终的逐行 URL 与公网/DNS 校验。重复链接会保留。',
    previewReady: '输入预览已就绪',
    nextStage: '逐行校验、部分成功结果和正式批量提交将在下一阶段接入。',
    refresh: '刷新状态',
  },
  'zh-tw': {
    title: '批次下載工作台', description: '貼上多條連結，或匯入 TXT / CSV。目前先核對格式、數量與本機引擎能力。', beta: '批次', ready: '本機引擎已支援批次', unsupported: '目前本機引擎需要升級後才能批次下載', offline: '本機引擎未連線', checking: '正在檢查本機引擎', inputLabel: '批次連結或 CSV 內容', placeholder: 'TXT：每行一個連結\n\nCSV：url,title\nhttps://example.com/video,標題', paste: '貼上', importFile: '匯入 TXT / CSV', clear: '清空', format: '輸入格式', auto: '自動識別', txt: 'TXT / 每行一個連結', csv: 'CSV', detected: '識別為 {format}', estimated: '預計 {count} 項', rows: '{count} 行', ignored: '忽略 {count} 行空白/註解', queue: '目前佇列 {count}/{capacity}', limits: '上限：100 萬字元 · 2000 行 · 500 項', tooManyChars: '輸入超過 100 萬字元上限', tooManyRows: '輸入超過 2000 行上限', tooManyItems: '預計項目超過 500 項上限', fileTooLarge: '檔案過大，無法作為批次輸入讀取', fileReadFailed: '無法讀取這個檔案', imported: '已匯入 {name}', previewNote: '這裡是快速預估，不取代 Local Engine 最終逐行 URL 與公網/DNS 驗證。重複連結會保留。', previewReady: '輸入預覽已就緒', nextStage: '逐行驗證、部分成功結果與正式批次提交將在下一階段接入。', refresh: '重新整理狀態',
  },
  en: {
    title: 'Batch download workbench', description: 'Paste multiple links or import TXT / CSV. This stage checks the format, size, and Local Engine capability first.', beta: 'Batch', ready: 'Local Engine supports batch downloads', unsupported: 'Upgrade the Local Engine to use batch downloads', offline: 'Local Engine is offline', checking: 'Checking Local Engine', inputLabel: 'Batch links or CSV content', placeholder: 'TXT: one link per line\n\nCSV: url,title\nhttps://example.com/video,Title', paste: 'Paste', importFile: 'Import TXT / CSV', clear: 'Clear', format: 'Input format', auto: 'Auto detect', txt: 'TXT / one link per line', csv: 'CSV', detected: 'Detected {format}', estimated: 'About {count} items', rows: '{count} rows', ignored: '{count} blank/comment rows ignored', queue: 'Queue {count}/{capacity}', limits: 'Limits: 1M characters · 2,000 rows · 500 items', tooManyChars: 'Input exceeds the 1M character limit', tooManyRows: 'Input exceeds the 2,000-row limit', tooManyItems: 'Estimated items exceed the 500-item limit', fileTooLarge: 'This file is too large to read as batch input', fileReadFailed: 'Could not read this file', imported: 'Imported {name}', previewNote: 'This is a fast estimate, not the final per-row URL and public-network/DNS validation performed by Local Engine. Duplicate links are preserved.', previewReady: 'Input preview is ready', nextStage: 'Per-row validation, partial-success results, and final batch submission are connected in the next stage.', refresh: 'Refresh status',
  },
  ja: {
    title: '一括ダウンロード', description: '複数のリンクを貼り付けるか TXT / CSV を読み込み、形式・件数・ローカルエンジン対応状況を確認します。', beta: '一括', ready: 'ローカルエンジンは一括処理に対応しています', unsupported: '一括ダウンロードにはローカルエンジンの更新が必要です', offline: 'ローカルエンジン未接続', checking: 'ローカルエンジンを確認中', inputLabel: '一括リンクまたは CSV', placeholder: 'TXT：1行に1リンク\n\nCSV：url,title\nhttps://example.com/video,タイトル', paste: '貼り付け', importFile: 'TXT / CSV を読込', clear: 'クリア', format: '入力形式', auto: '自動判定', txt: 'TXT / 1行1リンク', csv: 'CSV', detected: '{format} と判定', estimated: '約 {count} 件', rows: '{count} 行', ignored: '空白/コメント {count} 行を無視', queue: '待ち {count}/{capacity}', limits: '上限：100万文字 · 2000行 · 500件', tooManyChars: '100万文字の上限を超えています', tooManyRows: '2000行の上限を超えています', tooManyItems: '推定件数が500件を超えています', fileTooLarge: 'ファイルが大きすぎます', fileReadFailed: 'ファイルを読み込めませんでした', imported: '{name} を読み込みました', previewNote: 'これは簡易見積もりです。最終的な URL・公開ネットワーク/DNS 検証は Local Engine が各行に対して行います。重複リンクは保持されます。', previewReady: '入力プレビュー準備完了', nextStage: '行ごとの検証、部分成功結果、正式な一括送信は次段階で接続します。', refresh: '状態を更新',
  },
  es: {
    title: 'Lote de descargas', description: 'Pega varios enlaces o importa TXT / CSV. Primero se revisan el formato, la cantidad y la capacidad del motor local.', beta: 'Lote', ready: 'El motor local admite descargas por lotes', unsupported: 'Actualiza el motor local para usar descargas por lotes', offline: 'Motor local desconectado', checking: 'Comprobando el motor local', inputLabel: 'Enlaces por lote o contenido CSV', placeholder: 'TXT: un enlace por línea\n\nCSV: url,title\nhttps://example.com/video,Título', paste: 'Pegar', importFile: 'Importar TXT / CSV', clear: 'Limpiar', format: 'Formato', auto: 'Detectar automáticamente', txt: 'TXT / un enlace por línea', csv: 'CSV', detected: 'Detectado: {format}', estimated: 'Aprox. {count} elementos', rows: '{count} filas', ignored: '{count} filas vacías/comentarios ignoradas', queue: 'Cola {count}/{capacity}', limits: 'Límites: 1 M caracteres · 2000 filas · 500 elementos', tooManyChars: 'La entrada supera 1 M de caracteres', tooManyRows: 'La entrada supera 2000 filas', tooManyItems: 'La estimación supera 500 elementos', fileTooLarge: 'El archivo es demasiado grande', fileReadFailed: 'No se pudo leer el archivo', imported: '{name} importado', previewNote: 'Es una estimación rápida. Local Engine realiza después la validación final de URL y red pública/DNS por fila. Los enlaces duplicados se conservan.', previewReady: 'Vista previa lista', nextStage: 'La validación por fila, los resultados parciales y el envío final se conectarán en la siguiente etapa.', refresh: 'Actualizar estado',
  },
  ru: {
    title: 'Пакетная загрузка', description: 'Вставьте несколько ссылок или импортируйте TXT / CSV. Сначала проверяются формат, объём и поддержка Local Engine.', beta: 'Пакет', ready: 'Local Engine поддерживает пакетные загрузки', unsupported: 'Обновите Local Engine для пакетных загрузок', offline: 'Local Engine не подключён', checking: 'Проверка Local Engine', inputLabel: 'Пакет ссылок или CSV', placeholder: 'TXT: одна ссылка на строку\n\nCSV: url,title\nhttps://example.com/video,Название', paste: 'Вставить', importFile: 'Импорт TXT / CSV', clear: 'Очистить', format: 'Формат', auto: 'Автоопределение', txt: 'TXT / одна ссылка на строку', csv: 'CSV', detected: 'Определено: {format}', estimated: 'Примерно {count} элементов', rows: '{count} строк', ignored: 'Пропущено пустых/комментариев: {count}', queue: 'Очередь {count}/{capacity}', limits: 'Лимиты: 1 млн символов · 2000 строк · 500 элементов', tooManyChars: 'Превышен лимит 1 млн символов', tooManyRows: 'Превышен лимит 2000 строк', tooManyItems: 'Оценка превышает 500 элементов', fileTooLarge: 'Файл слишком большой', fileReadFailed: 'Не удалось прочитать файл', imported: 'Импортирован {name}', previewNote: 'Это быстрая оценка. Финальную проверку URL и публичной сети/DNS для каждой строки выполняет Local Engine. Дубликаты сохраняются.', previewReady: 'Предпросмотр готов', nextStage: 'Построчная проверка, частичный успех и окончательная отправка будут подключены на следующем этапе.', refresh: 'Обновить состояние',
  },
}

function copyFor(pathname: string | null): BatchCopy {
  const locale = pathname?.split('/').filter(Boolean)[0] || 'en'
  return COPY[locale] || COPY.en
}

type SubmitCopy = {
  submit: string
  submitting: string
  unavailable: string
  queueFull: string
  hint: string
  sent: string
  noneAccepted: string
}

const SUBMIT_COPY: Record<string, SubmitCopy> = {
  zh: { submit: '提交 {count} 项到本地队列', submitting: '正在提交批量任务', unavailable: '请先启动或升级 Local Engine', queueFull: '本地下载队列已满', hint: '提交后会立即启动首个可执行任务，其余任务继续使用当前 FIFO 队列；这不是多并发模式。', sent: '批量任务已发送', noneAccepted: '没有任务被本地引擎接收' },
  'zh-tw': { submit: '提交 {count} 項到本機佇列', submitting: '正在提交批次工作', unavailable: '請先啟動或升級 Local Engine', queueFull: '本機下載佇列已滿', hint: '提交後會立即啟動第一個可執行工作，其餘工作沿用目前 FIFO 佇列；這不是多重並行模式。', sent: '批次工作已送出', noneAccepted: '沒有工作被本機引擎接收' },
  en: { submit: 'Submit {count} items to local queue', submitting: 'Submitting batch', unavailable: 'Start or upgrade Local Engine first', queueFull: 'Local download queue is full', hint: 'The first runnable job starts immediately and the rest use the existing FIFO queue. This is not multi-job concurrency.', sent: 'Batch sent to Local Engine', noneAccepted: 'No jobs were accepted by Local Engine' },
  ja: { submit: '{count} 件をローカル待ちに送信', submitting: '一括ジョブを送信中', unavailable: 'Local Engine を起動または更新してください', queueFull: 'ローカルの待機キューが上限です', hint: '実行可能な先頭ジョブを開始し、残りは既存の FIFO キューに入ります。複数ジョブの同時実行ではありません。', sent: '一括ジョブを送信しました', noneAccepted: '受け付けられたジョブはありません' },
  es: { submit: 'Enviar {count} elementos a la cola local', submitting: 'Enviando lote', unavailable: 'Inicia o actualiza Local Engine', queueFull: 'La cola local está llena', hint: 'La primera tarea ejecutable comienza de inmediato y las demás usan la cola FIFO existente. No es concurrencia de varias tareas.', sent: 'Lote enviado al motor local', noneAccepted: 'El motor local no aceptó ninguna tarea' },
  ru: { submit: 'Отправить {count} элементов в локальную очередь', submitting: 'Отправка пакета', unavailable: 'Запустите или обновите Local Engine', queueFull: 'Локальная очередь заполнена', hint: 'Первая доступная задача запускается сразу, остальные остаются в существующей FIFO-очереди. Это не параллельное выполнение нескольких задач.', sent: 'Пакет отправлен в Local Engine', noneAccepted: 'Local Engine не принял ни одной задачи' },
}

function submitCopyFor(pathname: string | null): SubmitCopy {
  const locale = pathname?.split('/').filter(Boolean)[0] || 'en'
  return SUBMIT_COPY[locale] || SUBMIT_COPY.en
}

export function BatchWorkbench() {
  const pathname = usePathname()
  const copy = copyFor(pathname)
  const submitCopy = submitCopyFor(pathname)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [open, setOpen] = useState(false)
  const [input, setInput] = useState('')
  const [format, setFormat] = useState<BatchWorkbenchFormat>('auto')
  const [fileName, setFileName] = useState('')
  const [bridge, setBridge] = useState<LocalEngineBridgeStatus | null>(null)
  const [checkingBridge, setCheckingBridge] = useState(false)
  const [inputError, setInputError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submissionError, setSubmissionError] = useState('')
  const [submissionResult, setSubmissionResult] = useState<LocalEngineBatchSubmissionResult | null>(null)
  const [planOptions, setPlanOptions] = useState(() => createDefaultLocalEngineBatchPlanOptions())
  const [advancedOptions, setAdvancedOptions] = useState(() => createDefaultLocalEngineAdvancedOptions())

  const preview = useMemo(() => buildBatchWorkbenchPreview(input, format), [format, input])
  const canContinue = batchWorkbenchCanContinue(preview)
  const queueFull = Boolean(bridge?.busy && bridge.queueCapacity > 0 && bridge.queueLength >= bridge.queueCapacity)

  const refreshBridge = async () => {
    setCheckingBridge(true)
    try {
      setBridge(await getLocalEngineBridgeStatus())
    } finally {
      setCheckingBridge(false)
    }
  }

  useEffect(() => {
    if (!open) return
    let active = true
    const refresh = async () => {
      const next = await getLocalEngineBridgeStatus()
      if (active) setBridge(next)
    }
    void refresh()
    const timer = window.setInterval(() => void refresh(), 5000)
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [open])

  const handlePaste = async () => {
    try {
      const text = await navigator.clipboard.readText()
      setInput(text)
      setFileName('')
      setInputError('')
      setSubmissionResult(null)
      setSubmissionError('')
    } catch (error) {
      toast.error(copy.paste, { description: error instanceof Error ? error.message : String(error) })
    }
  }

  const handleFile = async (file: File | undefined) => {
    if (!file) return
    if (file.size > BATCH_WORKBENCH_MAX_FILE_BYTES) {
      setInputError(copy.fileTooLarge)
      return
    }
    try {
      const text = await file.text()
      if (text.length > BATCH_WORKBENCH_MAX_INPUT_CHARS) {
        setInputError(copy.tooManyChars)
        return
      }
      setInput(text)
      setFileName(file.name)
      setInputError('')
      setSubmissionResult(null)
      setSubmissionError('')
      toast.success(copy.imported.replace('{name}', file.name))
    } catch {
      setInputError(copy.fileReadFailed)
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const handleSubmitBatch = async () => {
    if (!canContinue || !bridge?.batchDownloadReady || queueFull || submitting) return
    setSubmitting(true)
    setSubmissionError('')
    setSubmissionResult(null)
    try {
      const result = await submitLocalEngineBatchInput({
        input,
        format,
        options: buildLocalEngineBatchOptions(
          planOptions,
          advancedOptions,
          Boolean(bridge?.aria2Ready),
        ),
      })
      setSubmissionResult(result)
      if (result.acceptedCount > 0) {
        toast.success(submitCopy.sent, { description: `${result.acceptedCount}/${result.inputCount}` })
      } else {
        toast.error(submitCopy.noneAccepted, { description: result.code })
      }
      await refreshBridge()
    } catch (error) {
      setSubmissionError(error instanceof Error ? error.message : String(error))
      await refreshBridge()
    } finally {
      setSubmitting(false)
    }
  }

  const limitError = preview.overCharacterLimit
    ? copy.tooManyChars
    : preview.overRowLimit
      ? copy.tooManyRows
      : preview.overItemLimit
        ? copy.tooManyItems
        : ''

  const statusText = checkingBridge
    ? copy.checking
    : bridge?.batchDownloadReady
      ? copy.ready
      : bridge
        ? copy.unsupported
        : copy.offline

  return (
    <details
      className="group mt-3 rounded-lg border bg-card"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary className="flex cursor-pointer list-none items-center gap-3 px-3 py-2.5 outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border bg-background">
          <ListChecks className="h-4 w-4" aria-hidden="true" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-2">
            <span className="truncate text-sm font-medium">{copy.title}</span>
            <span className="shrink-0 rounded border px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide text-muted-foreground">
              {copy.beta}
            </span>
          </div>
          <p className="mt-0.5 truncate text-[11px] text-muted-foreground">{copy.description}</p>
        </div>
        <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-150 group-open:rotate-180" aria-hidden="true" />
      </summary>

      <div className="border-t px-3 py-3">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 items-center gap-2 text-[11px]">
            <span className={`h-2 w-2 shrink-0 rounded-full ${bridge?.batchDownloadReady ? 'bg-emerald-600' : bridge ? 'bg-amber-500' : 'bg-muted-foreground/35'}`} aria-hidden="true" />
            <span className="truncate font-medium">{statusText}</span>
            {bridge ? (
              <span className="shrink-0 tabular-nums text-muted-foreground">v{bridge.version}</span>
            ) : null}
          </div>
          <Button type="button" variant="ghost" size="xs" className="self-start text-muted-foreground sm:self-auto" onClick={() => void refreshBridge()} disabled={checkingBridge}>
            {checkingBridge ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : <RotateCw className="h-3.5 w-3.5" aria-hidden="true" />}
            {copy.refresh}
          </Button>
        </div>

        <div className="mt-3 grid gap-2 lg:grid-cols-[minmax(0,1fr)_220px]">
          <div className="relative rounded-lg border bg-background focus-within:border-foreground/40">
            <label htmlFor="batch-workbench-input" className="sr-only">{copy.inputLabel}</label>
            <Textarea
              id="batch-workbench-input"
              value={input}
              onChange={(event) => {
                setInput(event.target.value)
                setFileName('')
                setInputError('')
                setSubmissionResult(null)
                setSubmissionError('')
              }}
              placeholder={copy.placeholder}
              className="min-h-[150px] resize-y border-0 bg-transparent px-3 py-2.5 font-mono text-xs leading-5 shadow-none focus-visible:ring-0"
            />
          </div>

          <div className="space-y-2">
            <label className="block space-y-1 text-[11px] font-medium text-muted-foreground">
              <span>{copy.format}</span>
              <Select
                value={format}
                onValueChange={(value) => {
                  setFormat(value as BatchWorkbenchFormat)
                  setSubmissionResult(null)
                  setSubmissionError('')
                }}
              >
                <SelectTrigger className="h-9 bg-background text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="auto">{copy.auto}</SelectItem>
                  <SelectItem value="txt">{copy.txt}</SelectItem>
                  <SelectItem value="csv">{copy.csv}</SelectItem>
                </SelectContent>
              </Select>
            </label>

            <input
              ref={fileInputRef}
              type="file"
              accept=".txt,.csv,text/plain,text/csv"
              className="hidden"
              onChange={(event) => void handleFile(event.target.files?.[0])}
            />
            <div className="grid grid-cols-2 gap-1.5">
              <Button type="button" variant="outline" size="sm" onClick={() => void handlePaste()}>
                <ClipboardPaste className="h-4 w-4" aria-hidden="true" />
                {copy.paste}
              </Button>
              <Button type="button" variant="outline" size="sm" onClick={() => fileInputRef.current?.click()}>
                <FileUp className="h-4 w-4" aria-hidden="true" />
                {copy.importFile}
              </Button>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="w-full text-muted-foreground"
              disabled={!input && !fileName}
              onClick={() => {
                setInput('')
                setFileName('')
                setInputError('')
                setSubmissionResult(null)
                setSubmissionError('')
              }}
            >
              <X className="h-4 w-4" aria-hidden="true" />
              {copy.clear}
            </Button>
          </div>
        </div>

        <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4" aria-live="polite">
          <div className="border-y px-1 py-2 text-xs">
            <div className="font-medium">{copy.detected.replace('{format}', preview.resolvedFormat.toUpperCase())}</div>
            <div className="mt-0.5 text-[10px] text-muted-foreground">{fileName || copy.format}</div>
          </div>
          <div className="border-y px-1 py-2 text-xs">
            <div className="font-medium tabular-nums">{copy.estimated.replace('{count}', String(preview.estimatedItems))}</div>
            <div className="mt-0.5 text-[10px] text-muted-foreground">{copy.rows.replace('{count}', String(preview.totalRows))}</div>
          </div>
          <div className="border-y px-1 py-2 text-xs">
            <div className="font-medium tabular-nums">{copy.ignored.replace('{count}', String(preview.ignoredRows))}</div>
            <div className="mt-0.5 text-[10px] text-muted-foreground">{copy.limits}</div>
          </div>
          <div className="border-y px-1 py-2 text-xs">
            <div className="font-medium tabular-nums">{copy.queue.replace('{count}', String(bridge?.queueLength || 0)).replace('{capacity}', String(bridge?.queueCapacity || '—'))}</div>
            <div className="mt-0.5 text-[10px] text-muted-foreground">{bridge?.batchDownloadReady ? copy.ready : statusText}</div>
          </div>
        </div>

        {inputError || limitError ? (
          <p role="alert" className="mt-2 text-[11px] font-medium text-destructive">{inputError || limitError}</p>
        ) : canContinue ? (
          <div className="mt-2 flex items-start gap-2 text-[11px] text-muted-foreground">
            <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-foreground" aria-hidden="true" />
            <div>
              <div className="font-medium text-foreground">{copy.previewReady}</div>
              <div className="mt-0.5 leading-4">{copy.previewNote}</div>
              <div className="mt-0.5 leading-4">{submitCopy.hint}</div>
            </div>
          </div>
        ) : (
          <p className="mt-2 text-[10px] leading-4 text-muted-foreground">{copy.previewNote}</p>
        )}

        <BatchDownloadPlanControls
          value={planOptions}
          disabled={submitting}
          onChange={(next) => {
            setPlanOptions(next)
            setSubmissionResult(null)
            setSubmissionError('')
          }}
        />

        <LocalEngineAdvancedControls
          value={advancedOptions}
          aria2Ready={Boolean(bridge?.aria2Ready)}
          disabled={submitting}
          onChange={(next) => {
            setAdvancedOptions(next)
            setSubmissionResult(null)
            setSubmissionError('')
          }}
        />

        <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <p className="min-w-0 text-[10px] leading-4 text-muted-foreground">{submitCopy.hint}</p>
          <Button
            type="button"
            size="sm"
            className="shrink-0 sm:min-w-56"
            disabled={!canContinue || !bridge?.batchDownloadReady || queueFull || submitting || Boolean(inputError || limitError)}
            onClick={() => void handleSubmitBatch()}
          >
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Send className="h-4 w-4" aria-hidden="true" />}
            {submitting
              ? submitCopy.submitting
              : queueFull
                ? submitCopy.queueFull
                : !bridge?.batchDownloadReady
                  ? submitCopy.unavailable
                  : submitCopy.submit.replace('{count}', String(preview.estimatedItems))}
          </Button>
        </div>

        {submissionError ? (
          <p role="alert" className="mt-2 text-[11px] font-medium text-destructive">{submissionError}</p>
        ) : null}

        <BatchWorkbenchResultPanel result={submissionResult} />

        <div className="mt-2 text-[9px] tabular-nums text-muted-foreground">
          {input.length.toLocaleString()} / {BATCH_WORKBENCH_MAX_INPUT_CHARS.toLocaleString()} · {preview.totalRows} / {BATCH_WORKBENCH_MAX_ROWS.toLocaleString()} · {preview.estimatedItems} / {BATCH_WORKBENCH_MAX_ITEMS}
        </div>
      </div>
    </details>
  )
}
