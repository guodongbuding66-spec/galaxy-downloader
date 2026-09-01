'use client';

import { useMemo } from 'react';
import { usePathname } from 'next/navigation';
import { ChevronDown, Gauge, Scissors, Subtitles } from 'lucide-react';

import type {
  LocalEngineSubtitleMode,
  SponsorBlockCategory,
} from '@/lib/local-engine';
import type { SubtitleTrack } from '@/lib/types';

export type LocalEngineAdvancedOptions = {
  segmentStart: string;
  segmentEnd: string;
  splitChapters: boolean;
  subtitleMode: LocalEngineSubtitleMode;
  subtitleLanguages: string[];
  audioLanguages: string[];
  sponsorBlockCategories: SponsorBlockCategory[];
  useAria2c: boolean;
};

type Copy = {
  title: string;
  summary: string;
  segment: string;
  start: string;
  end: string;
  segmentHint: string;
  splitChapters: string;
  subtitleMode: string;
  manual: string;
  auto: string;
  both: string;
  subtitleLanguages: string;
  detected: string;
  manualShort: string;
  autoShort: string;
  audioLanguages: string;
  audioHint: string;
  sponsorBlock: string;
  sponsor: string;
  selfPromo: string;
  interaction: string;
  aria2: string;
  aria2Ready: string;
  aria2Missing: string;
  offByDefault: string;
};

const COPY: Record<string, Copy> = {
  zh: {
    title: '高级本机下载',
    summary: '片段、章节、字幕/音轨、SponsorBlock、aria2c',
    segment: '视频片段',
    start: '开始',
    end: '结束',
    segmentHint: '例如 01:20 → 03:45；两项都留空则下载完整视频。',
    splitChapters: '按章节拆分为多个文件',
    subtitleMode: '字幕来源',
    manual: '人工字幕',
    auto: '自动字幕',
    both: '人工 + 自动',
    subtitleLanguages: '字幕语言',
    detected: '已检测',
    manualShort: '人工',
    autoShort: '自动',
    audioLanguages: '音轨语言',
    audioHint: '多音轨用逗号分隔，例如 zh,en,ja。留空由 yt-dlp 自动选择。',
    sponsorBlock: 'SponsorBlock（默认关闭）',
    sponsor: '赞助内容',
    selfPromo: '自我推广',
    interaction: '互动提醒',
    aria2: 'aria2c 高速下载',
    aria2Ready: '已检测到 aria2c；yt-dlp 仍负责解析与调度。',
    aria2Missing: '本机未检测到 aria2c，安装后重新连接即可启用。',
    offByDefault: '这些功能均为可选项，不会改变默认下载行为。',
  },
  'zh-tw': {
    title: '進階本機下載', summary: '片段、章節、字幕/音軌、SponsorBlock、aria2c', segment: '影片片段', start: '開始', end: '結束', segmentHint: '例如 01:20 → 03:45；兩項留空則下載完整影片。', splitChapters: '依章節拆分檔案', subtitleMode: '字幕來源', manual: '人工字幕', auto: '自動字幕', both: '人工 + 自動', subtitleLanguages: '字幕語言', detected: '已偵測', manualShort: '人工', autoShort: '自動', audioLanguages: '音軌語言', audioHint: '多音軌以逗號分隔，例如 zh,en,ja。留空由 yt-dlp 自動選擇。', sponsorBlock: 'SponsorBlock（預設關閉）', sponsor: '贊助內容', selfPromo: '自我推廣', interaction: '互動提醒', aria2: 'aria2c 高速下載', aria2Ready: '已偵測 aria2c；yt-dlp 仍負責解析與調度。', aria2Missing: '本機未偵測到 aria2c，安裝後重新連線即可啟用。', offByDefault: '這些功能皆為選用，不會改變預設下載行為。',
  },
  en: {
    title: 'Advanced local download', summary: 'Clips, chapters, tracks, SponsorBlock and aria2c', segment: 'Video segment', start: 'Start', end: 'End', segmentHint: 'Example 01:20 → 03:45. Leave both empty for the full video.', splitChapters: 'Split into chapter files', subtitleMode: 'Subtitle source', manual: 'Manual', auto: 'Auto-generated', both: 'Manual + auto', subtitleLanguages: 'Subtitle languages', detected: 'Detected', manualShort: 'manual', autoShort: 'auto', audioLanguages: 'Audio languages', audioHint: 'Comma-separated for multiple audio tracks, e.g. zh,en,ja. Empty lets yt-dlp choose.', sponsorBlock: 'SponsorBlock (off by default)', sponsor: 'Sponsor', selfPromo: 'Self-promotion', interaction: 'Interaction reminder', aria2: 'aria2c acceleration', aria2Ready: 'aria2c detected. yt-dlp still handles extraction and orchestration.', aria2Missing: 'aria2c was not detected locally. Install it and reconnect to enable acceleration.', offByDefault: 'All advanced features are optional and do not change the default download behavior.',
  },
  ja: {
    title: '高度なローカル保存', summary: '区間・チャプター・字幕/音声・SponsorBlock・aria2c', segment: '動画区間', start: '開始', end: '終了', segmentHint: '例 01:20 → 03:45。空欄なら全編を保存します。', splitChapters: 'チャプターごとに分割', subtitleMode: '字幕ソース', manual: '手動字幕', auto: '自動字幕', both: '手動 + 自動', subtitleLanguages: '字幕言語', detected: '検出', manualShort: '手動', autoShort: '自動', audioLanguages: '音声言語', audioHint: '複数音声は zh,en,ja のようにカンマ区切り。空欄は自動選択。', sponsorBlock: 'SponsorBlock（既定オフ）', sponsor: 'スポンサー', selfPromo: '自己宣伝', interaction: '操作案内', aria2: 'aria2c 高速化', aria2Ready: 'aria2c を検出。解析と制御は引き続き yt-dlp が担当します。', aria2Missing: 'aria2c が見つかりません。インストール後に再接続してください。', offByDefault: '高度な機能はすべて任意で、既定の保存動作は変わりません。',
  },
  es: {
    title: 'Descarga local avanzada', summary: 'Fragmentos, capítulos, pistas, SponsorBlock y aria2c', segment: 'Fragmento', start: 'Inicio', end: 'Fin', segmentHint: 'Ejemplo 01:20 → 03:45. Déjalo vacío para descargar el vídeo completo.', splitChapters: 'Separar por capítulos', subtitleMode: 'Origen de subtítulos', manual: 'Manuales', auto: 'Automáticos', both: 'Manuales + automáticos', subtitleLanguages: 'Idiomas de subtítulos', detected: 'Detectados', manualShort: 'manual', autoShort: 'auto', audioLanguages: 'Idiomas de audio', audioHint: 'Separa varias pistas con comas, p. ej. zh,en,ja. Vacío = selección automática.', sponsorBlock: 'SponsorBlock (apagado por defecto)', sponsor: 'Patrocinio', selfPromo: 'Autopromoción', interaction: 'Interacción', aria2: 'Aceleración aria2c', aria2Ready: 'aria2c detectado; yt-dlp sigue controlando la extracción.', aria2Missing: 'aria2c no está instalado o no fue detectado.', offByDefault: 'Todas estas opciones son voluntarias y no cambian la descarga predeterminada.',
  },
  ru: {
    title: 'Расширенная локальная загрузка', summary: 'Фрагменты, главы, дорожки, SponsorBlock и aria2c', segment: 'Фрагмент видео', start: 'Начало', end: 'Конец', segmentHint: 'Например 01:20 → 03:45. Оставьте поля пустыми для полного видео.', splitChapters: 'Разделять по главам', subtitleMode: 'Источник субтитров', manual: 'Ручные', auto: 'Автоматические', both: 'Ручные + авто', subtitleLanguages: 'Языки субтитров', detected: 'Найдено', manualShort: 'ручные', autoShort: 'авто', audioLanguages: 'Языки аудио', audioHint: 'Несколько дорожек через запятую, например zh,en,ja. Пусто = авто.', sponsorBlock: 'SponsorBlock (по умолчанию выключен)', sponsor: 'Реклама', selfPromo: 'Самореклама', interaction: 'Призывы', aria2: 'Ускорение aria2c', aria2Ready: 'aria2c обнаружен; yt-dlp по-прежнему управляет загрузкой.', aria2Missing: 'aria2c не обнаружен. Установите его и переподключите движок.', offByDefault: 'Все расширенные функции необязательны и не меняют поведение по умолчанию.',
  },
};

function localeCopy(pathname: string | null): Copy {
  const locale = pathname?.split('/').filter(Boolean)[0] || 'en';
  return COPY[locale] || COPY.en;
}

function listFromText(value: string): string[] {
  return [...new Set(value.split(/[\s,]+/).map((item) => item.trim()).filter(Boolean))].slice(0, 12);
}

function listText(values: string[]): string {
  return values.join(',');
}

function toggleCategory(
  values: SponsorBlockCategory[],
  category: SponsorBlockCategory,
): SponsorBlockCategory[] {
  return values.includes(category)
    ? values.filter((value) => value !== category)
    : [...values, category];
}

export function LocalEngineAdvancedControls({
  value,
  onChange,
  disabled = false,
  aria2Ready = false,
  subtitles = [],
}: {
  value: LocalEngineAdvancedOptions;
  onChange: (next: LocalEngineAdvancedOptions) => void;
  disabled?: boolean;
  aria2Ready?: boolean;
  subtitles?: SubtitleTrack[];
}) {
  const pathname = usePathname();
  const copy = localeCopy(pathname);
  const detectedSubtitles = useMemo(() => {
    const unique = new Map<string, SubtitleTrack>();
    for (const track of subtitles) {
      const language = track.language?.trim();
      if (!language) continue;
      const key = `${language}:${track.isAutoGenerated ? 'auto' : 'manual'}`;
      if (!unique.has(key)) unique.set(key, track);
    }
    return [...unique.values()].slice(0, 12);
  }, [subtitles]);

  const update = (changes: Partial<LocalEngineAdvancedOptions>) => {
    onChange({ ...value, ...changes });
  };

  const selectDetectedLanguage = (language: string) => {
    if (!language) return;
    const exists = value.subtitleLanguages.includes(language);
    update({
      subtitleLanguages: exists
        ? value.subtitleLanguages.filter((item) => item !== language)
        : [...value.subtitleLanguages, language].slice(0, 12),
    });
  };

  return (
    <details className="group mt-2 border-y py-1.5">
      <summary className="flex cursor-pointer list-none items-center gap-2 rounded-md py-1 text-[11px] outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <Gauge className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
        <span className="font-medium">{copy.title}</span>
        <span className="min-w-0 flex-1 truncate text-[10px] text-muted-foreground">{copy.summary}</span>
        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform duration-150 group-open:rotate-180" aria-hidden="true" />
      </summary>

      <div className="space-y-3 pb-1 pt-2.5">
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5 text-[11px] font-medium">
            <Scissors className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
            {copy.segment}
          </div>
          <div className="grid grid-cols-2 gap-2">
            <label className="space-y-1 text-[10px] text-muted-foreground">
              <span>{copy.start}</span>
              <input
                type="text"
                inputMode="numeric"
                value={value.segmentStart}
                disabled={disabled}
                placeholder="01:20"
                onChange={(event) => update({ segmentStart: event.target.value })}
                className="h-8 w-full rounded-md border bg-background px-2 text-xs tabular-nums text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
              />
            </label>
            <label className="space-y-1 text-[10px] text-muted-foreground">
              <span>{copy.end}</span>
              <input
                type="text"
                inputMode="numeric"
                value={value.segmentEnd}
                disabled={disabled}
                placeholder="03:45"
                onChange={(event) => update({ segmentEnd: event.target.value })}
                className="h-8 w-full rounded-md border bg-background px-2 text-xs tabular-nums text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
              />
            </label>
          </div>
          <p className="text-[10px] leading-4 text-muted-foreground">{copy.segmentHint}</p>
        </div>

        <label className="flex cursor-pointer items-center gap-2 text-[11px]">
          <input
            type="checkbox"
            checked={value.splitChapters}
            disabled={disabled}
            onChange={(event) => update({ splitChapters: event.target.checked })}
            className="h-3.5 w-3.5 accent-foreground"
          />
          <span>{copy.splitChapters}</span>
        </label>

        <div className="space-y-2 border-t pt-2.5">
          <div className="flex items-center gap-1.5 text-[11px] font-medium">
            <Subtitles className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
            {copy.subtitleMode}
          </div>
          <div className="grid grid-cols-3 gap-1 rounded-md border bg-background p-0.5">
            {([
              ['manual', copy.manual],
              ['auto', copy.auto],
              ['both', copy.both],
            ] as Array<[LocalEngineSubtitleMode, string]>).map(([mode, label]) => (
              <button
                key={mode}
                type="button"
                disabled={disabled}
                aria-pressed={value.subtitleMode === mode}
                onClick={() => update({ subtitleMode: mode })}
                className={`min-h-7 rounded px-1.5 text-[10px] font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50 ${value.subtitleMode === mode ? 'bg-foreground text-background' : 'text-muted-foreground hover:bg-muted hover:text-foreground'}`}
              >
                {label}
              </button>
            ))}
          </div>
          <label className="block space-y-1 text-[10px] text-muted-foreground">
            <span>{copy.subtitleLanguages}</span>
            <input
              type="text"
              value={listText(value.subtitleLanguages)}
              disabled={disabled}
              placeholder="zh-Hans,en"
              onChange={(event) => update({ subtitleLanguages: listFromText(event.target.value) })}
              className="h-8 w-full rounded-md border bg-background px-2 text-xs text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
            />
          </label>
          {detectedSubtitles.length ? (
            <div className="flex flex-wrap gap-1" aria-label={copy.detected}>
              {detectedSubtitles.map((track, index) => {
                const selected = value.subtitleLanguages.includes(track.language);
                return (
                  <button
                    key={`${track.language}-${track.isAutoGenerated ? 'auto' : 'manual'}-${index}`}
                    type="button"
                    disabled={disabled}
                    aria-pressed={selected}
                    onClick={() => selectDetectedLanguage(track.language)}
                    className={`rounded border px-1.5 py-0.5 text-[9px] outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50 ${selected ? 'border-foreground bg-foreground text-background' : 'text-muted-foreground hover:text-foreground'}`}
                  >
                    {track.language} · {track.isAutoGenerated ? copy.autoShort : copy.manualShort}
                  </button>
                );
              })}
            </div>
          ) : null}
        </div>

        <label className="block space-y-1 text-[10px] text-muted-foreground">
          <span>{copy.audioLanguages}</span>
          <input
            type="text"
            value={listText(value.audioLanguages)}
            disabled={disabled}
            placeholder="zh,en,ja"
            onChange={(event) => update({ audioLanguages: listFromText(event.target.value) })}
            className="h-8 w-full rounded-md border bg-background px-2 text-xs text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
          />
          <span className="block leading-4">{copy.audioHint}</span>
        </label>

        <div className="space-y-1.5 border-t pt-2.5">
          <div className="text-[11px] font-medium">{copy.sponsorBlock}</div>
          <div className="flex flex-wrap gap-x-4 gap-y-1.5">
            {([
              ['sponsor', copy.sponsor],
              ['selfpromo', copy.selfPromo],
              ['interaction', copy.interaction],
            ] as Array<[SponsorBlockCategory, string]>).map(([category, label]) => (
              <label key={category} className="flex cursor-pointer items-center gap-1.5 text-[10px] text-muted-foreground">
                <input
                  type="checkbox"
                  checked={value.sponsorBlockCategories.includes(category)}
                  disabled={disabled}
                  onChange={() => update({ sponsorBlockCategories: toggleCategory(value.sponsorBlockCategories, category) })}
                  className="h-3.5 w-3.5 accent-foreground"
                />
                {label}
              </label>
            ))}
          </div>
        </div>

        <label className={`flex items-start gap-2 border-t pt-2.5 text-[10px] ${aria2Ready ? 'cursor-pointer' : 'cursor-not-allowed opacity-60'}`}>
          <input
            type="checkbox"
            checked={aria2Ready && value.useAria2c}
            disabled={disabled || !aria2Ready}
            onChange={(event) => update({ useAria2c: event.target.checked })}
            className="mt-0.5 h-3.5 w-3.5 accent-foreground"
          />
          <span>
            <span className="block text-[11px] font-medium text-foreground">{copy.aria2}</span>
            <span className="mt-0.5 block leading-4 text-muted-foreground">{aria2Ready ? copy.aria2Ready : copy.aria2Missing}</span>
          </span>
        </label>

        <p className="text-[9px] leading-4 text-muted-foreground">{copy.offByDefault}</p>
      </div>
    </details>
  );
}
