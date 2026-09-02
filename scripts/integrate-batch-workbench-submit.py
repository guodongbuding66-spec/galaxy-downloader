from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src/components/downloader/BatchWorkbench.tsx"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "  RotateCw,\n  X,\n} from 'lucide-react'",
        "  RotateCw,\n  Send,\n  X,\n} from 'lucide-react'",
        "Send icon import",
    )

    text = replace_once(
        text,
        "import {\n  getLocalEngineBridgeStatus,\n  type LocalEngineBridgeStatus,\n} from '@/lib/local-engine-bridge'",
        "import {\n  getLocalEngineBridgeStatus,\n  submitLocalEngineBatchInput,\n  type LocalEngineBatchSubmissionResult,\n  type LocalEngineBridgeStatus,\n} from '@/lib/local-engine-bridge'",
        "batch bridge imports",
    )

    text = replace_once(
        text,
        "import {\n  BATCH_WORKBENCH_MAX_FILE_BYTES,",
        "import { BatchWorkbenchResultPanel } from './BatchWorkbenchResultPanel'\n\nimport {\n  BATCH_WORKBENCH_MAX_FILE_BYTES,",
        "result panel import",
    )

    marker = "function copyFor(pathname: string | null): BatchCopy {\n  const locale = pathname?.split('/').filter(Boolean)[0] || 'en'\n  return COPY[locale] || COPY.en\n}\n\n"
    submit_copy = """type SubmitCopy = {\n  submit: string\n  submitting: string\n  unavailable: string\n  queueFull: string\n  hint: string\n  sent: string\n  noneAccepted: string\n}\n\nconst SUBMIT_COPY: Record<string, SubmitCopy> = {\n  zh: { submit: '提交 {count} 项到本地队列', submitting: '正在提交批量任务', unavailable: '请先启动或升级 Local Engine', queueFull: '本地下载队列已满', hint: '提交后会立即启动首个可执行任务，其余任务继续使用当前 FIFO 队列；这不是多并发模式。', sent: '批量任务已发送', noneAccepted: '没有任务被本地引擎接收' },\n  'zh-tw': { submit: '提交 {count} 項到本機佇列', submitting: '正在提交批次工作', unavailable: '請先啟動或升級 Local Engine', queueFull: '本機下載佇列已滿', hint: '提交後會立即啟動第一個可執行工作，其餘工作沿用目前 FIFO 佇列；這不是多重並行模式。', sent: '批次工作已送出', noneAccepted: '沒有工作被本機引擎接收' },\n  en: { submit: 'Submit {count} items to local queue', submitting: 'Submitting batch', unavailable: 'Start or upgrade Local Engine first', queueFull: 'Local download queue is full', hint: 'The first runnable job starts immediately and the rest use the existing FIFO queue. This is not multi-job concurrency.', sent: 'Batch sent to Local Engine', noneAccepted: 'No jobs were accepted by Local Engine' },\n  ja: { submit: '{count} 件をローカル待ちに送信', submitting: '一括ジョブを送信中', unavailable: 'Local Engine を起動または更新してください', queueFull: 'ローカルの待機キューが上限です', hint: '実行可能な先頭ジョブを開始し、残りは既存の FIFO キューに入ります。複数ジョブの同時実行ではありません。', sent: '一括ジョブを送信しました', noneAccepted: '受け付けられたジョブはありません' },\n  es: { submit: 'Enviar {count} elementos a la cola local', submitting: 'Enviando lote', unavailable: 'Inicia o actualiza Local Engine', queueFull: 'La cola local está llena', hint: 'La primera tarea ejecutable comienza de inmediato y las demás usan la cola FIFO existente. No es concurrencia de varias tareas.', sent: 'Lote enviado al motor local', noneAccepted: 'El motor local no aceptó ninguna tarea' },\n  ru: { submit: 'Отправить {count} элементов в локальную очередь', submitting: 'Отправка пакета', unavailable: 'Запустите или обновите Local Engine', queueFull: 'Локальная очередь заполнена', hint: 'Первая доступная задача запускается сразу, остальные остаются в существующей FIFO-очереди. Это не параллельное выполнение нескольких задач.', sent: 'Пакет отправлен в Local Engine', noneAccepted: 'Local Engine не принял ни одной задачи' },\n}\n\nfunction submitCopyFor(pathname: string | null): SubmitCopy {\n  const locale = pathname?.split('/').filter(Boolean)[0] || 'en'\n  return SUBMIT_COPY[locale] || SUBMIT_COPY.en\n}\n\n"""
    text = replace_once(text, marker, marker + submit_copy, "submit copy")

    text = replace_once(
        text,
        "  const copy = copyFor(pathname)\n  const fileInputRef",
        "  const copy = copyFor(pathname)\n  const submitCopy = submitCopyFor(pathname)\n  const fileInputRef",
        "submit copy usage",
    )

    text = replace_once(
        text,
        "  const [checkingBridge, setCheckingBridge] = useState(false)\n  const [inputError, setInputError] = useState('')\n",
        "  const [checkingBridge, setCheckingBridge] = useState(false)\n  const [inputError, setInputError] = useState('')\n  const [submitting, setSubmitting] = useState(false)\n  const [submissionError, setSubmissionError] = useState('')\n  const [submissionResult, setSubmissionResult] = useState<LocalEngineBatchSubmissionResult | null>(null)\n",
        "submission state",
    )

    text = replace_once(
        text,
        "  const preview = useMemo(() => buildBatchWorkbenchPreview(input, format), [format, input])\n  const canContinue = batchWorkbenchCanContinue(preview)\n",
        "  const preview = useMemo(() => buildBatchWorkbenchPreview(input, format), [format, input])\n  const canContinue = batchWorkbenchCanContinue(preview)\n  const queueFull = Boolean(bridge?.busy && bridge.queueCapacity > 0 && bridge.queueLength >= bridge.queueCapacity)\n\n  useEffect(() => {\n    setSubmissionResult(null)\n    setSubmissionError('')\n  }, [format, input])\n",
        "submission reset",
    )

    insert_after = """  const handleFile = async (file: File | undefined) => {\n    if (!file) return\n    if (file.size > BATCH_WORKBENCH_MAX_FILE_BYTES) {\n      setInputError(copy.fileTooLarge)\n      return\n    }\n    try {\n      const text = await file.text()\n      if (text.length > BATCH_WORKBENCH_MAX_INPUT_CHARS) {\n        setInputError(copy.tooManyChars)\n        return\n      }\n      setInput(text)\n      setFileName(file.name)\n      setInputError('')\n      toast.success(copy.imported.replace('{name}', file.name))\n    } catch {\n      setInputError(copy.fileReadFailed)\n    } finally {\n      if (fileInputRef.current) fileInputRef.current.value = ''\n    }\n  }\n\n"""
    submit_handler = """  const handleSubmitBatch = async () => {\n    if (!canContinue || !bridge?.batchDownloadReady || queueFull || submitting) return\n    setSubmitting(true)\n    setSubmissionError('')\n    setSubmissionResult(null)\n    try {\n      const result = await submitLocalEngineBatchInput({ input, format })\n      setSubmissionResult(result)\n      if (result.acceptedCount > 0) {\n        toast.success(submitCopy.sent, { description: `${result.acceptedCount}/${result.inputCount}` })\n      } else {\n        toast.error(submitCopy.noneAccepted, { description: result.code })\n      }\n      await refreshBridge()\n    } catch (error) {\n      setSubmissionError(error instanceof Error ? error.message : String(error))\n      await refreshBridge()\n    } finally {\n      setSubmitting(false)\n    }\n  }\n\n"""
    text = replace_once(text, insert_after, insert_after + submit_handler, "submit handler")

    text = replace_once(
        text,
        "              <div className=\"mt-0.5 leading-4\">{copy.nextStage}</div>\n",
        "              <div className=\"mt-0.5 leading-4\">{submitCopy.hint}</div>\n",
        "preview submission hint",
    )

    counter = """        <div className=\"mt-2 text-[9px] tabular-nums text-muted-foreground\">\n          {input.length.toLocaleString()} / {BATCH_WORKBENCH_MAX_INPUT_CHARS.toLocaleString()} · {preview.totalRows} / {BATCH_WORKBENCH_MAX_ROWS.toLocaleString()} · {preview.estimatedItems} / {BATCH_WORKBENCH_MAX_ITEMS}\n        </div>\n"""
    controls = """        <div className=\"mt-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between\">\n          <p className=\"min-w-0 text-[10px] leading-4 text-muted-foreground\">{submitCopy.hint}</p>\n          <Button\n            type=\"button\"\n            size=\"sm\"\n            className=\"shrink-0 sm:min-w-56\"\n            disabled={!canContinue || !bridge?.batchDownloadReady || queueFull || submitting || Boolean(inputError || limitError)}\n            onClick={() => void handleSubmitBatch()}\n          >\n            {submitting ? <Loader2 className=\"h-4 w-4 animate-spin\" aria-hidden=\"true\" /> : <Send className=\"h-4 w-4\" aria-hidden=\"true\" />}\n            {submitting\n              ? submitCopy.submitting\n              : queueFull\n                ? submitCopy.queueFull\n                : !bridge?.batchDownloadReady\n                  ? submitCopy.unavailable\n                  : submitCopy.submit.replace('{count}', String(preview.estimatedItems))}\n          </Button>\n        </div>\n\n        {submissionError ? (\n          <p role=\"alert\" className=\"mt-2 text-[11px] font-medium text-destructive\">{submissionError}</p>\n        ) : null}\n\n        <BatchWorkbenchResultPanel result={submissionResult} />\n\n""" + counter
    text = replace_once(text, counter, controls, "submission controls")

    TARGET.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
