'use client';

import { useMemo } from 'react';
import { usePathname } from 'next/navigation';
import {
  ChevronDown,
  Gauge,
  RotateCcw,
  Scissors,
  Sparkles,
  Subtitles,
  Zap,
} from 'lucide-react';

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

type ExtraCopy = {
  presets: string;
  standard: string;
  course: string;
  clean: string;
  fast: string;
  intro: string;
  outro: string;
  preview: string;
  musicOfftopic: string;
  filler: string;
  reset: string;
  active: string;
  standardHint: string;
  courseHint: string;
  cleanHint: string;
  fastHint: string;
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

const EXTRA: Record<string, ExtraCopy> = {
  zh: {
    presets: '快捷方案', standard: '标准', course: '课程 / 播客', clean: '去赞助', fast: '高速', intro: '片头', outro: '片尾', preview: '预告 / 回顾', musicOfftopic: '离题音乐', filler: '填充片段', reset: '恢复默认', active: '项已启用', standardHint: '恢复完整视频与标准 yt-dlp 行为', courseHint: '按章节拆分，适合课程、播客和长视频', cleanHint: '移除赞助、自我推广和互动提醒', fastHint: '启用 aria2c，多连接下载由 yt-dlp 调度',
  },
  'zh-tw': {
    presets: '快速方案', standard: '標準', course: '課程 / Podcast', clean: '去贊助', fast: '高速', intro: '片頭', outro: '片尾', preview: '預告 / 回顧', musicOfftopic: '離題音樂', filler: '填充片段', reset: '恢復預設', active: '項已啟用', standardHint: '恢復完整影片與標準 yt-dlp 行為', courseHint: '依章節拆分，適合課程、Podcast 與長影片', cleanHint: '移除贊助、自我推廣與互動提醒', fastHint: '啟用 aria2c，由 yt-dlp 調度多連線下載',
  },
  en: {
    presets: 'Quick presets', standard: 'Standard', course: 'Course / podcast', clean: 'Remove sponsors', fast: 'Fast', intro: 'Intro', outro: 'Outro', preview: 'Preview / recap', musicOfftopic: 'Off-topic music', filler: 'Filler', reset: 'Reset defaults', active: 'active', standardHint: 'Full video with standard yt-dlp behavior', courseHint: 'Split chapters for courses, podcasts and long-form media', cleanHint: 'Remove sponsor, self-promo and interaction segments', fastHint: 'Enable aria2c while yt-dlp keeps orchestration',
  },
  ja: {
    presets: 'クイック設定', standard: '標準', course: '講座 / Podcast', clean: 'スポンサー除去', fast: '高速', intro: 'イントロ', outro: 'アウトロ', preview: '予告 / 振り返り', musicOfftopic: '無関係な音楽', filler: '埋め草', reset: '既定に戻す', active: '項目有効', standardHint: '全編を標準の yt-dlp 動作で保存', courseHint: '講座・Podcast・長編をチャプター分割', cleanHint: 'スポンサー・自己宣伝・操作案内を除去', fastHint: 'aria2c を有効化し、yt-dlp が制御',
  },
  es: {
    presets: 'Ajustes rápidos', standard: 'Estándar', course: 'Curso / podcast', clean: 'Quitar patrocinio', fast: 'Rápido', intro: 'Introducción', outro: 'Cierre', preview: 'Avance / resumen', musicOfftopic: 'Música ajena', filler: 'Relleno', reset: 'Restablecer', active: 'activos', standardHint: 'Vídeo completo con el comportamiento estándar de yt-dlp', courseHint: 'Divide capítulos para cursos, podcasts y vídeos largos', cleanHint: 'Elimina patrocinio, autopromoción e interacción', fastHint: 'Activa aria2c manteniendo yt-dlp como orquestador',
  },
  ru: {
    presets: 'Быстрые профили', standard: 'Стандарт', course: 'Курс / подкаст', clean: 'Убрать рекламу', fast: 'Быстро', intro: 'Интро', outro: 'Аутро', preview: 'Анонс / повтор', musicOfftopic: 'Посторонняя музыка', filler: 'Заполнитель', reset: 'Сбросить', active: 'включено', standardHint: 'Полное видео со стандартным поведением yt-dlp', courseHint: 'Разделение по главам для курсов, подкастов и длинных видео', cleanHint: 'Удалить рекламу, саморекламу и призывы', fastHint: 'Включить aria2c, сохранив управление за yt-dlp',
  },
};

function locale(pathname: string | null): string {
  return pathname?.split('/').filter(Boolean)[0] || 'en';
}

function listFromText(value: string): string[] {
  return [...new Set(value.split(/[\s,]+/).map((item) => item.trim()).filter(Boolean))].slice(0, 12);
}

function listText(values: string[]): string {
  return values.join(',');
}

function toggleCategory(values: SponsorBlockCategory[], category: SponsorBlockCategory): SponsorBlockCategory[] {
  return values.includes(category)
    ? values.filter((value) => value !== category)
    : [...values, category];
}

function defaultOptions(): LocalEngineAdvancedOptions {
  return {
    segmentStart: '',
    segmentEnd: '',
    splitChapters: false,
    subtitleMode: 'both',
    subtitleLanguages: [],
    audioLanguages: [],
    sponsorBlockCategories: [],
    useAria2c: false,
  };
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
  const language = locale(pathname);
  const copy = COPY[language] || COPY.en;
  const extra = EXTRA[language] || EXTRA.en;
  const detectedSubtitles = useMemo(() => {
    const unique = new Map<string, SubtitleTrack>();
    for (const track of subtitles) {
      const trackLanguage = track.language?.trim();
      if (!trackLanguage) continue;
      const key = `${trackLanguage}:${track.isAutoGenerated ? 'auto' : 'manual'}`;
      if (!unique.has(key)) unique.set(key, track);
    }
    return [...unique.values()].slice(0, 12);
  }, [subtitles]);

  const activeCount = useMemo(() => {
    let count = 0;
    if (value.segmentStart || value.segmentEnd) count += 1;
    if (value.splitChapters) count += 1;
    if (value.subtitleLanguages.length) count += 1;
    if (value.audioLanguages.length) count += 1;
    if (value.sponsorBlockCategories.length) count += 1;
    if (value.useAria2c) count += 1;
    return count;
  }, [value]);

  const update = (changes: Partial<LocalEngineAdvancedOptions>) => {
    onChange({ ...value, ...changes });
  };

  const applyPreset = (preset: 'standard' | 'course' | 'clean' | 'fast') => {
    const base = defaultOptions();
    if (preset === 'course') {
      onChange({ ...base, splitChapters: true, subtitleMode: 'both' });
      return;
    }
    if (preset === 'clean') {
      onChange({ ...base, sponsorBlockCategories: ['sponsor', 'selfpromo', 'interaction'] });
      return;
    }
    if (preset === 'fast') {
      onChange({ ...base, useAria2c: aria2Ready });
      return;
    }
    onChange(base);
  };

  const selectDetectedLanguage = (trackLanguage: string) => {
    if (!trackLanguage) return;
    const exists = value.subtitleLanguages.includes(trackLanguage);
    update({
      subtitleLanguages: exists
        ? value.subtitleLanguages.filter((item) => item !== trackLanguage)
        : [...value.subtitleLanguages, trackLanguage].slice(0, 12),
    });
  };

  const sponsorOptions: Array<[SponsorBlockCategory, string]> = [
    ['sponsor', copy.sponsor],
    ['selfpromo', copy.selfPromo],
    ['interaction', copy.interaction],
    ['intro', extra.intro],
    ['outro', extra.outro],
    ['preview', extra.preview],
    ['music_offtopic', extra.musicOfftopic],
    ['filler', extra.filler],
  ];

  const presetOptions: Array<{
    id: 'standard' | 'course' | 'clean' | 'fast';
    label: string;
    hint: string;
    disabled?: boolean;
  }> = [
    { id: 'standard', label: extra.standard, hint: extra.standardHint },
    { id: 'course', label: extra.course, hint: extra.courseHint },
    { id: 'clean', label: extra.clean, hint: extra.cleanHint },
    { id: 'fast', label: extra.fast, hint: extra.fastHint, disabled: !aria2Ready },
  ];

  return (
    <details className="group mt-2 overflow-hidden rounded-xl border bg-card/40">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2.5 text-[11px] outline-none transition-colors hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring">
        <Gauge className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
        <span className="font-semibold">{copy.title}</span>
        <span className="min-w-0 flex-1 truncate text-[10px] text-muted-foreground">{copy.summary}</span>
        {activeCount > 0 ? (
          <span className="rounded-full border bg-background px-1.5 py-0.5 text-[9px] font-medium tabular-nums text-muted-foreground">
            {activeCount} {extra.active}
          </span>
        ) : null}
        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform duration-150 group-open:rotate-180" aria-hidden="true" />
      </summary>

      <div className="border-t px-3 pb-3 pt-2.5">
        <div className="mb-3 space-y-1.5">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-1.5 text-[11px] font-medium">
              <Sparkles className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
              {extra.presets}
            </div>
            <button
              type="button"
              disabled={disabled}
              onClick={() => onChange(defaultOptions())}
              className="inline-flex h-7 items-center gap-1 rounded-md px-2 text-[10px] text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
            >
              <RotateCcw className="h-3 w-3" aria-hidden="true" />
              {extra.reset}
            </button>
          </div>
          <div className="grid grid-cols-2 gap-1.5 md:grid-cols-4">
            {presetOptions.map((preset) => (
              <button
                key={preset.id}
                type="button"
                disabled={disabled || preset.disabled}
                onClick={() => applyPreset(preset.id)}
                title={preset.hint}
                className="min-h-9 rounded-lg border bg-background px-2 py-1.5 text-left outline-none transition-colors hover:border-foreground/30 hover:bg-muted/50 focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-40"
              >
                <span className="block text-[10px] font-semibold">{preset.label}</span>
                <span className="mt-0.5 block truncate text-[9px] text-muted-foreground">{preset.hint}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="grid gap-3 lg:grid-cols-2">
          <div className="space-y-3">
            <section className="rounded-lg border bg-background/60 p-2.5">
              <div className="flex items-center gap-1.5 text-[11px] font-medium">
                <Scissors className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
                {copy.segment}
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2">
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
              <p className="mt-1.5 text-[9px] leading-4 text-muted-foreground">{copy.segmentHint}</p>
              <label className="mt-2 flex cursor-pointer items-center gap-2 text-[10px]">
                <input
                  type="checkbox"
                  checked={value.splitChapters}
                  disabled={disabled}
                  onChange={(event) => update({ splitChapters: event.target.checked })}
                  className="h-3.5 w-3.5 accent-foreground"
                />
                <span>{copy.splitChapters}</span>
              </label>
            </section>

            <section className="rounded-lg border bg-background/60 p-2.5">
              <div className="flex items-center gap-1.5 text-[11px] font-medium">
                <Subtitles className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
                {copy.subtitleMode}
              </div>
              <div className="mt-2 grid grid-cols-3 gap-1 rounded-md border bg-card p-0.5">
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
              <label className="mt-2 block space-y-1 text-[10px] text-muted-foreground">
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
                <div className="mt-1.5 flex flex-wrap gap-1" aria-label={copy.detected}>
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
              <label className="mt-2 block space-y-1 text-[10px] text-muted-foreground">
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
            </section>
          </div>

          <div className="space-y-3">
            <section className="rounded-lg border bg-background/60 p-2.5">
              <div className="text-[11px] font-medium">{copy.sponsorBlock}</div>
              <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-2">
                {sponsorOptions.map(([category, label]) => (
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
            </section>

            <section className="rounded-lg border bg-background/60 p-2.5">
              <label className={`flex items-start gap-2 text-[10px] ${aria2Ready ? 'cursor-pointer' : 'cursor-not-allowed opacity-60'}`}>
                <input
                  type="checkbox"
                  checked={aria2Ready && value.useAria2c}
                  disabled={disabled || !aria2Ready}
                  onChange={(event) => update({ useAria2c: event.target.checked })}
                  className="mt-0.5 h-3.5 w-3.5 accent-foreground"
                />
                <span>
                  <span className="flex items-center gap-1 text-[11px] font-medium text-foreground">
                    <Zap className="h-3 w-3" aria-hidden="true" />
                    {copy.aria2}
                  </span>
                  <span className="mt-0.5 block leading-4 text-muted-foreground">{aria2Ready ? copy.aria2Ready : copy.aria2Missing}</span>
                </span>
              </label>
            </section>

            <p className="px-0.5 text-[9px] leading-4 text-muted-foreground">{copy.offByDefault}</p>
          </div>
        </div>
      </div>
    </details>
  );
}
