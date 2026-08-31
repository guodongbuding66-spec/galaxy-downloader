'use client';

import { useMemo, useRef, useState } from 'react';
import { usePathname } from 'next/navigation';
import {
    Captions,
    Check,
    Film,
    Loader2,
    Music,
    PackageCheck,
    ShieldCheck,
    Video,
    X,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select';
import { toast } from '@/lib/deferred-toast';
import {
    AUDIO_QUALITY_PRESETS,
    buildSourceMediaDownloadUrl,
    getSubtitleDisplayName,
    normalizeQualityOptions,
    resolveSourceMediaDownloadUrl,
    resolveSubtitleUrl,
    type QualityChoice,
} from '@/lib/media-download-options';
import {
    createFinalMediaFile,
    type FinalMediaProgress,
    type FinalMediaStage,
} from '@/lib/final-media-export';
import type { SubtitleTrack, UnifiedParseResult, VideoQualityOption } from '@/lib/types';
import { formatBytes, sanitizeFilename } from '@/lib/utils';

import { LocalEngineDownloadCard } from './LocalEngineDownloadCard';

type ResultData = NonNullable<UnifiedParseResult['data']>;
const EMPTY_SUBTITLES: SubtitleTrack[] = [];

type Copy = {
    title: string;
    intro: string;
    videoQuality: string;
    audioQuality: string;
    best: string;
    includeAudio: string;
    includeSubtitle: string;
    subtitleTrack: string;
    noSubtitle: string;
    includeCover: string;
    coverUnavailable: string;
    output: string;
    outputValue: string;
    outputHint: string;
    start: string;
    cancel: string;
    completed: string;
    failed: string;
    fallback: string;
    currentPlan: string;
    planVideo: string;
    planAudio: string;
    planSubtitle: string;
    planCover: string;
    finalOnly: string;
    stages: Record<FinalMediaStage, string>;
};

const COPY: Record<string, Copy> = {
    zh: {
        title: '成品下载',
        intro: '一次选择，一次处理，只输出一个最终 MP4。系统会自动获取所选画质与音质，并按需把字幕和封面写入同一个视频文件。',
        videoQuality: '视频画质',
        audioQuality: '音频质量',
        best: '最佳可用',
        includeAudio: '合并最佳音频',
        includeSubtitle: '内嵌字幕',
        subtitleTrack: '字幕轨道',
        noSubtitle: '当前解析结果没有可用字幕',
        includeCover: '内嵌封面',
        coverUnavailable: '当前解析结果没有封面',
        output: '输出格式',
        outputValue: 'MP4 · 单一成品文件',
        outputHint: '视频默认流复制，不二次压缩；音频统一封装为 AAC；字幕作为可开关字幕轨；封面作为视频封面写入文件。',
        start: '生成并下载成品',
        cancel: '取消处理',
        completed: '成品已生成并开始下载',
        failed: '成品生成失败',
        fallback: '所选质量接口不可用，已自动尝试解析结果中的可用媒体流。',
        currentPlan: '当前成品方案',
        planVideo: '视频',
        planAudio: '音频',
        planSubtitle: '字幕',
        planCover: '封面',
        finalOnly: '不会分别下载视频、音频、字幕或封面；这些资源只用于生成最终成品。',
        stages: {
            resolving: '正在解析所选媒体流',
            'downloading-video': '正在获取视频轨',
            'downloading-audio': '正在获取音频轨',
            'downloading-subtitle': '正在获取字幕',
            'downloading-cover': '正在获取封面',
            'loading-ffmpeg': '正在启动合成引擎',
            assembling: '正在封装成单一 MP4',
            saving: '正在生成最终文件',
            completed: '处理完成',
        },
    },
    'zh-tw': {
        title: '成品下載',
        intro: '一次選擇、一次處理，只輸出一個最終 MP4。系統會自動取得所選畫質與音質，並依需要把字幕與封面寫入同一個影片檔。',
        videoQuality: '影片畫質',
        audioQuality: '音訊品質',
        best: '最佳可用',
        includeAudio: '合併最佳音訊',
        includeSubtitle: '內嵌字幕',
        subtitleTrack: '字幕軌道',
        noSubtitle: '目前沒有可用字幕',
        includeCover: '內嵌封面',
        coverUnavailable: '目前沒有封面',
        output: '輸出格式',
        outputValue: 'MP4 · 單一成品檔案',
        outputHint: '影片預設直接複製串流、不二次壓縮；音訊封裝為 AAC；字幕為可切換字幕軌；封面寫入影片檔。',
        start: '產生並下載成品',
        cancel: '取消處理',
        completed: '成品已產生並開始下載',
        failed: '成品產生失敗',
        fallback: '所選品質介面不可用，已自動嘗試解析結果中的可用媒體串流。',
        currentPlan: '目前成品方案',
        planVideo: '影片',
        planAudio: '音訊',
        planSubtitle: '字幕',
        planCover: '封面',
        finalOnly: '不會分別下載影片、音訊、字幕或封面；這些資源只用來產生最終成品。',
        stages: {
            resolving: '正在解析所選媒體串流',
            'downloading-video': '正在取得影片軌',
            'downloading-audio': '正在取得音訊軌',
            'downloading-subtitle': '正在取得字幕',
            'downloading-cover': '正在取得封面',
            'loading-ffmpeg': '正在啟動合成引擎',
            assembling: '正在封裝成單一 MP4',
            saving: '正在產生最終檔案',
            completed: '處理完成',
        },
    },
    en: {
        title: 'Finished video download',
        intro: 'Choose once and receive one final MP4. The app automatically fetches the selected video/audio quality and optionally embeds subtitles and a cover into the same file.',
        videoQuality: 'Video quality',
        audioQuality: 'Audio quality',
        best: 'Best available',
        includeAudio: 'Merge best audio',
        includeSubtitle: 'Embed subtitles',
        subtitleTrack: 'Subtitle track',
        noSubtitle: 'No subtitle track is available',
        includeCover: 'Embed cover',
        coverUnavailable: 'No cover is available',
        output: 'Output',
        outputValue: 'MP4 · one finished file',
        outputHint: 'Video is stream-copied without re-encoding; audio is normalized to AAC; subtitles remain selectable; the cover is stored as an attached picture.',
        start: 'Build and download final video',
        cancel: 'Cancel processing',
        completed: 'Final video created and download started',
        failed: 'Failed to build final video',
        fallback: 'The selected-quality endpoint was unavailable, so available parsed media streams were tried automatically.',
        currentPlan: 'Final output plan',
        planVideo: 'Video',
        planAudio: 'Audio',
        planSubtitle: 'Subtitles',
        planCover: 'Cover',
        finalOnly: 'Video, audio, subtitle and cover assets are not downloaded separately; they are used only to build the final file.',
        stages: {
            resolving: 'Resolving selected media streams',
            'downloading-video': 'Fetching video track',
            'downloading-audio': 'Fetching audio track',
            'downloading-subtitle': 'Fetching subtitles',
            'downloading-cover': 'Fetching cover',
            'loading-ffmpeg': 'Starting media engine',
            assembling: 'Muxing one MP4 file',
            saving: 'Preparing final file',
            completed: 'Completed',
        },
    },
    ja: {
        title: '完成動画ダウンロード',
        intro: '画質・音質を一度選ぶだけで、最終的な MP4 を 1 本生成します。必要に応じて字幕とカバーも同じ動画ファイルに組み込みます。',
        videoQuality: '動画画質',
        audioQuality: '音声品質',
        best: '利用可能な最高品質',
        includeAudio: '高品質音声を結合',
        includeSubtitle: '字幕を埋め込む',
        subtitleTrack: '字幕トラック',
        noSubtitle: '利用可能な字幕はありません',
        includeCover: 'カバーを埋め込む',
        coverUnavailable: '利用可能なカバーはありません',
        output: '出力形式',
        outputValue: 'MP4 · 完成ファイル 1 本',
        outputHint: '動画は可能な限り再エンコードせずコピーし、音声は AAC に統一します。字幕は切り替え可能なトラックとして、カバーは動画の添付画像として保存します。',
        start: '完成動画を生成してダウンロード',
        cancel: '処理をキャンセル',
        completed: '完成動画を生成し、ダウンロードを開始しました',
        failed: '完成動画の生成に失敗しました',
        fallback: '選択した品質の取得先が利用できないため、解析結果内の利用可能なメディアを自動的に試します。',
        currentPlan: '現在の出力プラン',
        planVideo: '動画',
        planAudio: '音声',
        planSubtitle: '字幕',
        planCover: 'カバー',
        finalOnly: '動画・音声・字幕・カバーを個別には保存せず、最終ファイルの生成にのみ使用します。',
        stages: {
            resolving: '選択したメディアを解析中',
            'downloading-video': '動画トラックを取得中',
            'downloading-audio': '音声トラックを取得中',
            'downloading-subtitle': '字幕を取得中',
            'downloading-cover': 'カバーを取得中',
            'loading-ffmpeg': 'メディアエンジンを起動中',
            assembling: '1 本の MP4 にまとめています',
            saving: '最終ファイルを準備中',
            completed: '処理完了',
        },
    },
    es: {
        title: 'Descarga de vídeo final',
        intro: 'Elige una vez la calidad de vídeo y audio y obtén un único MP4 final. Los subtítulos y la portada pueden integrarse en el mismo archivo.',
        videoQuality: 'Calidad de vídeo',
        audioQuality: 'Calidad de audio',
        best: 'Mejor disponible',
        includeAudio: 'Combinar audio de alta calidad',
        includeSubtitle: 'Integrar subtítulos',
        subtitleTrack: 'Pista de subtítulos',
        noSubtitle: 'No hay subtítulos disponibles',
        includeCover: 'Integrar portada',
        coverUnavailable: 'No hay portada disponible',
        output: 'Salida',
        outputValue: 'MP4 · un único archivo final',
        outputHint: 'El vídeo se copia sin recodificar cuando es posible; el audio se normaliza a AAC; los subtítulos quedan seleccionables y la portada se adjunta al vídeo.',
        start: 'Crear y descargar el vídeo final',
        cancel: 'Cancelar procesamiento',
        completed: 'Vídeo final creado y descarga iniciada',
        failed: 'No se pudo crear el vídeo final',
        fallback: 'La fuente de la calidad seleccionada no está disponible; se probarán automáticamente los flujos disponibles del resultado analizado.',
        currentPlan: 'Plan de salida actual',
        planVideo: 'Vídeo',
        planAudio: 'Audio',
        planSubtitle: 'Subtítulos',
        planCover: 'Portada',
        finalOnly: 'El vídeo, audio, subtítulos y portada no se descargan por separado; solo se utilizan para generar el archivo final.',
        stages: {
            resolving: 'Resolviendo los flujos seleccionados',
            'downloading-video': 'Obteniendo pista de vídeo',
            'downloading-audio': 'Obteniendo pista de audio',
            'downloading-subtitle': 'Obteniendo subtítulos',
            'downloading-cover': 'Obteniendo portada',
            'loading-ffmpeg': 'Iniciando el motor multimedia',
            assembling: 'Empaquetando un único MP4',
            saving: 'Preparando el archivo final',
            completed: 'Completado',
        },
    },
    ru: {
        title: 'Загрузка готового видео',
        intro: 'Один раз выберите качество видео и аудио и получите один итоговый MP4. При необходимости субтитры и обложка будут встроены в тот же файл.',
        videoQuality: 'Качество видео',
        audioQuality: 'Качество аудио',
        best: 'Лучшее доступное',
        includeAudio: 'Объединить качественное аудио',
        includeSubtitle: 'Встроить субтитры',
        subtitleTrack: 'Дорожка субтитров',
        noSubtitle: 'Доступных субтитров нет',
        includeCover: 'Встроить обложку',
        coverUnavailable: 'Доступной обложки нет',
        output: 'Формат вывода',
        outputValue: 'MP4 · один готовый файл',
        outputHint: 'Видео по возможности копируется без повторного кодирования; аудио приводится к AAC; субтитры остаются переключаемой дорожкой, а обложка прикрепляется к видео.',
        start: 'Создать и скачать готовое видео',
        cancel: 'Отменить обработку',
        completed: 'Готовое видео создано, загрузка началась',
        failed: 'Не удалось создать готовое видео',
        fallback: 'Источник выбранного качества недоступен, поэтому будут автоматически проверены доступные потоки из результата разбора.',
        currentPlan: 'Текущий план вывода',
        planVideo: 'Видео',
        planAudio: 'Аудио',
        planSubtitle: 'Субтитры',
        planCover: 'Обложка',
        finalOnly: 'Видео, аудио, субтитры и обложка не сохраняются отдельно и используются только для создания итогового файла.',
        stages: {
            resolving: 'Определение выбранных медиапотоков',
            'downloading-video': 'Получение видеодорожки',
            'downloading-audio': 'Получение аудиодорожки',
            'downloading-subtitle': 'Получение субтитров',
            'downloading-cover': 'Получение обложки',
            'loading-ffmpeg': 'Запуск медиа-движка',
            assembling: 'Сборка одного MP4',
            saving: 'Подготовка итогового файла',
            completed: 'Готово',
        },
    },
};

function copyFor(pathname: string | null): Copy {
    const locale = pathname?.split('/').filter(Boolean)[0] || 'en';
    return COPY[locale] || COPY.en;
}

function resolveScopedCapabilities(result: ResultData): {
    qualityOptions?: VideoQualityOption[];
    subtitles?: SubtitleTrack[];
    videoUrl?: string | null;
    audioUrl?: string | null;
    cover?: string | null;
} {
    const currentPage = result.pages?.find((page) => page.page === result.currentPage);
    const currentVideo = result.videos?.find((video) => video.id === result.currentItemId);

    return {
        qualityOptions: currentVideo?.qualityOptions?.length
            ? currentVideo.qualityOptions
            : currentPage?.qualityOptions?.length
                ? currentPage.qualityOptions
                : result.qualityOptions,
        subtitles: currentVideo?.subtitles?.length
            ? currentVideo.subtitles
            : currentPage?.subtitles?.length
                ? currentPage.subtitles
                : result.subtitles,
        videoUrl: currentVideo?.downloadVideoUrl
            || currentVideo?.originDownloadVideoUrl
            || currentPage?.downloadVideoUrl
            || result.downloadVideoUrl
            || result.originDownloadVideoUrl,
        audioUrl: currentVideo?.downloadAudioUrl
            || currentVideo?.originDownloadAudioUrl
            || currentPage?.downloadAudioUrl
            || result.downloadAudioUrl
            || result.originDownloadAudioUrl,
        cover: currentVideo?.cover || result.cover,
    };
}

function resolveScopedSourceUrl(result: ResultData): string {
    const sourceUrl = typeof result.url === 'string' ? result.url.trim() : '';
    if (!sourceUrl) return '';

    if ((result.platform === 'bili' || result.platform === 'bilibili') && result.currentPage) {
        try {
            const url = new URL(sourceUrl);
            url.searchParams.set('p', String(result.currentPage));
            return url.toString();
        } catch {
            return sourceUrl;
        }
    }

    return sourceUrl;
}

function subtitleKey(track: SubtitleTrack, index: number): string {
    return track.id || `${track.language}-${index}`;
}

function CheckboxRow({
    checked,
    disabled,
    label,
    hint,
    onChange,
}: {
    checked: boolean;
    disabled?: boolean;
    label: string;
    hint?: string;
    onChange: (checked: boolean) => void;
}) {
    return (
        <label
            className={`flex min-h-11 items-center gap-3 rounded-xl bg-muted/20 px-3 py-2.5 ring-1 ring-border/70 transition-colors duration-150 ${
                disabled
                    ? 'cursor-not-allowed opacity-50'
                    : 'cursor-pointer hover:bg-muted/35 focus-within:ring-2 focus-within:ring-ring'
            }`}
        >
            <input
                type="checkbox"
                checked={checked}
                disabled={disabled}
                onChange={(event) => onChange(event.target.checked)}
                className="h-4 w-4 shrink-0 accent-primary focus-visible:outline-none"
            />
            <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium leading-5">{label}</span>
                {hint && <span className="mt-0.5 block text-xs leading-4 text-muted-foreground text-pretty">{hint}</span>}
            </span>
        </label>
    );
}

function qualityLabel(option: QualityChoice): string {
    return [
        option.label || option.quality,
        option.filesize ? formatBytes(option.filesize) : null,
    ].filter(Boolean).join(' · ');
}

export function AdvancedDownloadOptions({ result }: { result: ResultData }) {
    const pathname = usePathname();
    const copy = copyFor(pathname);
    const capabilities = resolveScopedCapabilities(result);
    const qualityOptions = useMemo(
        () => normalizeQualityOptions(capabilities.qualityOptions),
        [capabilities.qualityOptions],
    );
    const parserBest = qualityOptions.find((option) => option.source === 'parser') || null;
    const subtitles = capabilities.subtitles ?? EMPTY_SUBTITLES;
    const firstSubtitleKey = subtitles[0] ? subtitleKey(subtitles[0], 0) : '';
    const sourceUrl = resolveScopedSourceUrl(result);

    const [videoQuality, setVideoQuality] = useState('best');
    const [audioQuality, setAudioQuality] = useState('best');
    const [includeAudio, setIncludeAudio] = useState(true);
    const [includeSubtitle, setIncludeSubtitle] = useState(subtitles.length > 0);
    const [subtitleId, setSubtitleId] = useState(firstSubtitleKey);
    const [includeCover, setIncludeCover] = useState(Boolean(capabilities.cover));
    const [progress, setProgress] = useState<FinalMediaProgress | null>(null);
    const [running, setRunning] = useState(false);
    const abortRef = useRef<AbortController | null>(null);

    const selectedQuality = qualityOptions.find((option) => option.quality === videoQuality) || qualityOptions[0];
    const effectiveVideoQuality = videoQuality === 'best' && parserBest ? parserBest : selectedQuality;
    const effectiveSubtitleId = subtitles.some((track, index) => subtitleKey(track, index) === subtitleId)
        ? subtitleId
        : firstSubtitleKey;
    const selectedSubtitle = subtitles.find((track, index) => subtitleKey(track, index) === effectiveSubtitleId) || null;
    const canComposeVideo = result.kind !== 'audio'
        && result.noteType !== 'audio'
        && result.noteType !== 'image'
        && result.videoAudioMode !== 'pure_music';

    if (!sourceUrl || !canComposeVideo) return null;

    const resolveVideoUrl = async (): Promise<{ url: string; usedFallback: boolean }> => {
        if (effectiveVideoQuality?.downloadUrl) {
            return { url: effectiveVideoQuality.downloadUrl, usedFallback: false };
        }

        try {
            const requestUrl = buildSourceMediaDownloadUrl({
                sourceUrl,
                type: 'video',
                quality: effectiveVideoQuality?.quality || 'best',
                formatId: effectiveVideoQuality?.formatId,
            });
            return { url: await resolveSourceMediaDownloadUrl(requestUrl), usedFallback: false };
        } catch (error) {
            if (capabilities.videoUrl) {
                console.warn('Falling back to parsed video URL:', error);
                return { url: capabilities.videoUrl, usedFallback: true };
            }
            throw error;
        }
    };

    const resolveAudioUrl = async (): Promise<{ url: string | null; usedFallback: boolean }> => {
        if (!includeAudio) return { url: null, usedFallback: false };
        try {
            const requestUrl = buildSourceMediaDownloadUrl({
                sourceUrl,
                type: 'audio',
                quality: audioQuality,
            });
            return { url: await resolveSourceMediaDownloadUrl(requestUrl), usedFallback: false };
        } catch (error) {
            if (capabilities.audioUrl) {
                console.warn('Falling back to parsed audio URL:', error);
                return { url: capabilities.audioUrl, usedFallback: true };
            }
            console.warn('No separate audio stream available; preserving video audio if present:', error);
            return { url: null, usedFallback: true };
        }
    };

    const startFinalExport = async () => {
        if (running) return;
        const controller = new AbortController();
        abortRef.current = controller;
        setRunning(true);
        setProgress({ stage: 'resolving', progress: 1 });

        try {
            const [video, audio] = await Promise.all([
                resolveVideoUrl(),
                resolveAudioUrl(),
            ]);
            const usedFallback = video.usedFallback || audio.usedFallback;
            if (usedFallback) toast.message(copy.fallback);

            const subtitleUrl = includeSubtitle && selectedSubtitle
                ? resolveSubtitleUrl(selectedSubtitle)
                : null;
            const coverUrl = includeCover ? capabilities.cover || null : null;

            await createFinalMediaFile({
                title: sanitizeFilename(result.title || 'media'),
                videoUrl: video.url,
                audioUrl: audio.url,
                subtitleUrl,
                subtitleLanguage: selectedSubtitle?.language || null,
                subtitleFormat: selectedSubtitle?.format || null,
                coverUrl,
                sourceUrl,
                signal: controller.signal,
                onProgress: setProgress,
            });
            toast.success(copy.completed);
        } catch (error) {
            if (error instanceof DOMException && error.name === 'AbortError') {
                return;
            }
            console.error('Final media export failed:', error);
            toast.error(copy.failed, {
                description: error instanceof Error ? error.message : String(error),
            });
        } finally {
            abortRef.current = null;
            setRunning(false);
        }
    };

    const cancel = () => {
        abortRef.current?.abort();
        abortRef.current = null;
        setRunning(false);
        setProgress(null);
    };

    const subtitleText = includeSubtitle && selectedSubtitle
        ? getSubtitleDisplayName(selectedSubtitle)
        : '—';
    const selectedAudioLabel = AUDIO_QUALITY_PRESETS.find((item) => item.quality === audioQuality)?.label || audioQuality;

    const localEnginePlan = {
        videoSelection: effectiveVideoQuality
            ? {
                quality: effectiveVideoQuality.quality,
                label: effectiveVideoQuality.label,
                height: effectiveVideoQuality.height,
            }
            : null,
        audioQuality,
        includeAudio,
        includeSubtitle: includeSubtitle && Boolean(selectedSubtitle),
        subtitleLanguage: selectedSubtitle?.language || null,
        includeCover: includeCover && Boolean(capabilities.cover),
    };

    return (
        <section className="overflow-hidden rounded-2xl border bg-card shadow-sm">
            <div className="border-b bg-muted/20 p-4 sm:p-5">
                <div className="flex items-start gap-3">
                    <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-background ring-1 ring-border">
                        <PackageCheck className="h-4 w-4" aria-hidden="true" />
                    </div>
                    <div className="min-w-0 flex-1">
                        <h3 className="text-base font-semibold tracking-tight sm:text-lg">{copy.title}</h3>
                        <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground text-pretty">{copy.intro}</p>
                    </div>
                </div>
            </div>

            <div className="grid gap-5 p-4 sm:p-5">
                <div className="space-y-5">
                    <div className="grid gap-4 rounded-xl bg-muted/20 p-4 ring-1 ring-border/70">
                        <div className="space-y-2">
                            <div className="flex items-center gap-2 text-sm font-medium">
                                <Video className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                                {copy.videoQuality}
                            </div>
                            <Select value={videoQuality} onValueChange={setVideoQuality} disabled={running}>
                                <SelectTrigger className="h-11 bg-background">
                                    <SelectValue placeholder={copy.best} />
                                </SelectTrigger>
                                <SelectContent>
                                    {qualityOptions.map((option) => (
                                        <SelectItem key={option.quality} value={option.quality}>
                                            {qualityLabel(option)}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>

                        <div className="space-y-2">
                            <div className="flex items-center gap-2 text-sm font-medium">
                                <Music className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                                {copy.audioQuality}
                            </div>
                            <Select value={audioQuality} onValueChange={setAudioQuality} disabled={running || !includeAudio}>
                                <SelectTrigger className="h-11 bg-background">
                                    <SelectValue placeholder={copy.best} />
                                </SelectTrigger>
                                <SelectContent>
                                    {AUDIO_QUALITY_PRESETS.map((option) => (
                                        <SelectItem key={option.quality} value={option.quality}>
                                            {option.label}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>
                    </div>

                    <div className="space-y-3">
                        <div className="grid gap-2">
                            <CheckboxRow
                                checked={includeAudio}
                                disabled={running}
                                onChange={setIncludeAudio}
                                label={copy.includeAudio}
                                hint={selectedAudioLabel}
                            />
                            <CheckboxRow
                                checked={includeSubtitle && subtitles.length > 0}
                                disabled={running || subtitles.length === 0}
                                onChange={setIncludeSubtitle}
                                label={copy.includeSubtitle}
                                hint={subtitles.length ? subtitleText : copy.noSubtitle}
                            />
                            <CheckboxRow
                                checked={includeCover && Boolean(capabilities.cover)}
                                disabled={running || !capabilities.cover}
                                onChange={setIncludeCover}
                                label={copy.includeCover}
                                hint={capabilities.cover ? undefined : copy.coverUnavailable}
                            />
                        </div>

                        {includeSubtitle && subtitles.length > 0 && (
                            <div className="space-y-2 rounded-xl bg-muted/20 p-4 ring-1 ring-border/70">
                                <div className="flex items-center gap-2 text-sm font-medium">
                                    <Captions className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                                    {copy.subtitleTrack}
                                </div>
                                <Select value={effectiveSubtitleId} onValueChange={setSubtitleId} disabled={running}>
                                    <SelectTrigger className="h-11 bg-background">
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {subtitles.map((track, index) => (
                                            <SelectItem key={subtitleKey(track, index)} value={subtitleKey(track, index)}>
                                                {getSubtitleDisplayName(track)}{track.format ? ` · ${track.format.toUpperCase()}` : ''}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                        )}
                    </div>
                </div>

                <div className="space-y-3">
                    <div className="rounded-xl border bg-background p-4 shadow-sm">
                        <div className="mb-3 flex items-center gap-2 text-sm font-semibold">
                            <Film className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                            {copy.currentPlan}
                        </div>
                        <dl className="space-y-2.5 text-sm">
                            <div className="flex items-start justify-between gap-4">
                                <dt className="shrink-0 text-muted-foreground">{copy.planVideo}</dt>
                                <dd className="min-w-0 text-end font-medium break-words">{qualityLabel(effectiveVideoQuality || qualityOptions[0])}</dd>
                            </div>
                            <div className="flex items-start justify-between gap-4">
                                <dt className="shrink-0 text-muted-foreground">{copy.planAudio}</dt>
                                <dd className="min-w-0 text-end font-medium break-words">{includeAudio ? selectedAudioLabel : '—'}</dd>
                            </div>
                            <div className="flex items-start justify-between gap-4">
                                <dt className="shrink-0 text-muted-foreground">{copy.planSubtitle}</dt>
                                <dd className="min-w-0 text-end font-medium break-words">{includeSubtitle ? subtitleText : '—'}</dd>
                            </div>
                            <div className="flex items-start justify-between gap-4">
                                <dt className="shrink-0 text-muted-foreground">{copy.planCover}</dt>
                                <dd className="font-medium">
                                    {includeCover && capabilities.cover ? <Check className="h-4 w-4" aria-hidden="true" /> : '—'}
                                </dd>
                            </div>
                        </dl>
                        <div className="mt-4 flex items-start gap-2 border-t pt-3 text-xs leading-5 text-muted-foreground">
                            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                            <span>{copy.outputHint}</span>
                        </div>
                    </div>

                    <LocalEngineDownloadCard
                        result={result}
                        plan={localEnginePlan}
                        disabled={running}
                    />

                    {progress && (
                        <div className="space-y-2.5 rounded-xl border bg-background p-4 shadow-sm" role="status" aria-live="polite">
                            <div className="flex items-center justify-between gap-3 text-sm">
                                <span className="flex min-w-0 items-center gap-2 font-medium">
                                    {running ? (
                                        <Loader2 className="h-4 w-4 shrink-0 animate-spin" aria-hidden="true" />
                                    ) : (
                                        <Check className="h-4 w-4 shrink-0" aria-hidden="true" />
                                    )}
                                    <span className="min-w-0 text-pretty">{copy.stages[progress.stage]}</span>
                                </span>
                                <span className="shrink-0 tabular-nums text-muted-foreground">{Math.round(progress.progress)}%</span>
                            </div>
                            <Progress value={progress.progress} />
                            {progress.loaded && progress.total ? (
                                <div className="text-xs tabular-nums text-muted-foreground">
                                    {formatBytes(progress.loaded)} / {formatBytes(progress.total)}
                                </div>
                            ) : null}
                        </div>
                    )}

                    <div className="space-y-2 rounded-xl bg-muted/20 p-3 ring-1 ring-border/70">
                        {running ? (
                            <Button type="button" variant="destructive" size="lg" className="min-h-11 w-full font-semibold" onClick={cancel}>
                                <X className="h-4 w-4" aria-hidden="true" />
                                {copy.cancel}
                            </Button>
                        ) : (
                            <Button type="button" size="lg" className="min-h-11 w-full font-semibold" onClick={startFinalExport}>
                                <PackageCheck className="h-4 w-4" aria-hidden="true" />
                                {copy.start}
                            </Button>
                        )}
                        <p className="px-1 text-center text-xs leading-5 text-muted-foreground text-pretty">
                            {copy.outputValue} · {copy.finalOnly}
                        </p>
                    </div>
                </div>
            </div>
        </section>
    );
}
