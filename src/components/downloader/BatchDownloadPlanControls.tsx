'use client'

import { usePathname } from 'next/navigation'
import { Download, FileArchive, ImageIcon, Music2, Subtitles, Video } from 'lucide-react'

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  AUDIO_QUALITY_PRESETS,
  VIDEO_QUALITY_PRESETS,
} from '@/lib/media-download-options'
import type { LocalEngineBatchPlanOptions } from '@/lib/local-engine-batch-options'

type Copy = {
  title: string
  summary: string
  videoQuality: string
  audioQuality: string
  includeAudio: string
  includeSubtitle: string
  includeCover: string
  archive: string
  archiveHint: string
}

const COPY: Record<string, Copy> = {
  zh: {
    title: '批量下载参数',
    summary: '这些设置会应用到本批次每一个有效任务',
    videoQuality: '视频画质',
    audioQuality: '音频质量',
    includeAudio: '保留 / 合并音频',
    includeSubtitle: '下载字幕',
    includeCover: '下载封面',
    archive: '跳过已下载内容',
    archiveHint: '默认关闭。开启后使用本机 Download Archive；重复链接仍会保留在批量输入中，但已记录成功的媒体可被 yt-dlp 跳过。',
  },
  'zh-tw': {
    title: '批次下載參數', summary: '這些設定會套用到本批次每一個有效工作', videoQuality: '影片畫質', audioQuality: '音訊品質', includeAudio: '保留 / 合併音訊', includeSubtitle: '下載字幕', includeCover: '下載封面', archive: '略過已下載內容', archiveHint: '預設關閉。開啟後使用本機 Download Archive；重複連結仍會保留，但已成功記錄的媒體可由 yt-dlp 略過。',
  },
  en: {
    title: 'Batch download plan', summary: 'These settings apply to every valid job in this batch', videoQuality: 'Video quality', audioQuality: 'Audio quality', includeAudio: 'Keep / merge audio', includeSubtitle: 'Download subtitles', includeCover: 'Download cover', archive: 'Skip previously downloaded', archiveHint: 'Off by default. When enabled, the local Download Archive may skip media already recorded as successfully downloaded; duplicate input rows are still preserved.',
  },
  ja: {
    title: '一括ダウンロード設定', summary: 'この設定を一括内のすべての有効ジョブに適用します', videoQuality: '動画品質', audioQuality: '音声品質', includeAudio: '音声を保持 / 結合', includeSubtitle: '字幕を保存', includeCover: 'カバーを保存', archive: '保存済みをスキップ', archiveHint: '既定はオフです。有効にすると Local Download Archive を使用し、成功済みのメディアを yt-dlp がスキップできます。重複入力行自体は保持されます。',
  },
  es: {
    title: 'Plan de descarga por lote', summary: 'Estos ajustes se aplican a cada tarea válida del lote', videoQuality: 'Calidad de vídeo', audioQuality: 'Calidad de audio', includeAudio: 'Conservar / combinar audio', includeSubtitle: 'Descargar subtítulos', includeCover: 'Descargar portada', archive: 'Omitir lo ya descargado', archiveHint: 'Desactivado por defecto. Al activarlo, el Download Archive local puede omitir medios ya registrados como descargados correctamente; las filas duplicadas se conservan.',
  },
  ru: {
    title: 'Параметры пакетной загрузки', summary: 'Настройки применяются ко всем допустимым задачам пакета', videoQuality: 'Качество видео', audioQuality: 'Качество аудио', includeAudio: 'Сохранить / объединить аудио', includeSubtitle: 'Скачать субтитры', includeCover: 'Скачать обложку', archive: 'Пропускать уже загруженное', archiveHint: 'По умолчанию выключено. При включении локальный Download Archive позволяет yt-dlp пропускать уже успешно загруженные медиа; повторяющиеся строки входных данных сохраняются.',
  },
}

function copyFor(pathname: string | null): Copy {
  const locale = pathname?.split('/').filter(Boolean)[0] || 'en'
  return COPY[locale] || COPY.en
}

function Toggle({
  checked,
  disabled,
  label,
  icon: Icon,
  onChange,
}: {
  checked: boolean
  disabled: boolean
  label: string
  icon: typeof Music2
  onChange: (checked: boolean) => void
}) {
  return (
    <label className="flex min-h-8 cursor-pointer items-center gap-2 text-[10px] disabled:cursor-not-allowed">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
        className="h-3.5 w-3.5 accent-foreground"
      />
      <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
      <span>{label}</span>
    </label>
  )
}

export function BatchDownloadPlanControls({
  value,
  onChange,
  disabled = false,
}: {
  value: LocalEngineBatchPlanOptions
  onChange: (next: LocalEngineBatchPlanOptions) => void
  disabled?: boolean
}) {
  const pathname = usePathname()
  const copy = copyFor(pathname)
  const update = (changes: Partial<LocalEngineBatchPlanOptions>) => onChange({ ...value, ...changes })

  return (
    <details className="group mt-3 overflow-hidden rounded-xl border bg-card/40">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2.5 text-[11px] outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <Download className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
        <span className="font-semibold">{copy.title}</span>
        <span className="min-w-0 flex-1 truncate text-[10px] text-muted-foreground">{copy.summary}</span>
      </summary>

      <div className="border-t px-3 pb-3 pt-2.5">
        <div className="grid gap-2 sm:grid-cols-2">
          <label className="space-y-1 text-[10px] font-medium text-muted-foreground">
            <span className="flex items-center gap-1.5"><Video className="h-3.5 w-3.5" aria-hidden="true" />{copy.videoQuality}</span>
            <Select value={value.videoQuality} onValueChange={(next) => update({ videoQuality: next })} disabled={disabled}>
              <SelectTrigger className="h-8 bg-background text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                {VIDEO_QUALITY_PRESETS.map((option) => (
                  <SelectItem key={option.quality} value={option.quality}>{option.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>

          <label className="space-y-1 text-[10px] font-medium text-muted-foreground">
            <span className="flex items-center gap-1.5"><Music2 className="h-3.5 w-3.5" aria-hidden="true" />{copy.audioQuality}</span>
            <Select value={value.audioQuality} onValueChange={(next) => update({ audioQuality: next })} disabled={disabled || !value.includeAudio}>
              <SelectTrigger className="h-8 bg-background text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                {AUDIO_QUALITY_PRESETS.map((option) => (
                  <SelectItem key={option.quality} value={option.quality}>{option.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
        </div>

        <div className="mt-2 grid gap-x-4 gap-y-1 border-y py-1.5 sm:grid-cols-2 lg:grid-cols-4">
          <Toggle checked={value.includeAudio} disabled={disabled} label={copy.includeAudio} icon={Music2} onChange={(checked) => update({ includeAudio: checked })} />
          <Toggle checked={value.includeSubtitle} disabled={disabled} label={copy.includeSubtitle} icon={Subtitles} onChange={(checked) => update({ includeSubtitle: checked })} />
          <Toggle checked={value.includeCover} disabled={disabled} label={copy.includeCover} icon={ImageIcon} onChange={(checked) => update({ includeCover: checked })} />
          <Toggle checked={value.skipPreviouslyDownloaded} disabled={disabled} label={copy.archive} icon={FileArchive} onChange={(checked) => update({ skipPreviouslyDownloaded: checked })} />
        </div>
        <p className="mt-1.5 text-[9px] leading-4 text-muted-foreground">{copy.archiveHint}</p>
      </div>
    </details>
  )
}
