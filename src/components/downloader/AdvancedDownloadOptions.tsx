'use client';

import { useMemo, useRef, useState } from 'react';
import { usePathname } from 'next/navigation';
import { Captions, Check, Loader2, Music, PackageCheck, Video, X } from 'lucide-react';

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
    browserAction: string;
    cancel: string;
    completed: string;
    failed: string;
    fallback: string;
    finalOnly: string;
    stages: Record<FinalMediaStage, string>;
};

const COPY: Record<string, Copy> = {
    zh: {
        title: '下载方案',
        intro: '默认：最佳画质 + 最佳音频，只生成一个最终视频。字幕和封面默认关闭，需要时再开启。',
        videoQuality: '画质',
        audioQuality: '音质',
        best: '最佳可用',
        includeAudio: '合并音频',
        includeSubtitle: '内嵌字幕',
        subtitleTrack: '字幕轨道',
        noSubtitle: '无可用字幕',
        includeCover: '内嵌封面',
        coverUnavailable: '无可用封面',
        browserAction: '浏览器合成下载',
        cancel: '取消处理',
        completed: '最终视频已生成',
        failed: '生成最终视频失败',
        fallback: '所选媒体流不可用，已自动切换到解析结果中的可用流。',
        finalOnly: '不会把视频轨、音频轨、字幕或封面分别保存为多份文件。',
        stages: {
            resolving: '解析媒体流',
            'downloading-video': '获取视频轨',
            'downloading-audio': '获取音频轨',
            'downloading-subtitle': '获取字幕',
            'downloading-cover': '获取封面',
            'loading-ffmpeg': '启动合成引擎',
            assembling: '封装最终视频',
            saving: '保存文件',
            completed: '完成',
        },
    },
    'zh-tw': {
        title: '下載方案', intro: '預設：最佳畫質 + 最佳音訊，只產生一個最終影片。字幕與封面預設關閉。', videoQuality: '畫質', audioQuality: '音質', best: '最佳可用', includeAudio: '合併音訊', includeSubtitle: '內嵌字幕', subtitleTrack: '字幕軌道', noSubtitle: '無可用字幕', includeCover: '內嵌封面', coverUnavailable: '無可用封面', browserAction: '瀏覽器合成下載', cancel: '取消處理', completed: '最終影片已產生', failed: '產生最終影片失敗', fallback: '所選媒體流不可用，已切換到可用串流。', finalOnly: '不會把影片、音訊、字幕或封面分別保存成多個檔案。',
        stages: { resolving: '解析媒體', 'downloading-video': '取得影片', 'downloading-audio': '取得音訊', 'downloading-subtitle': '取得字幕', 'downloading-cover': '取得封面', 'loading-ffmpeg': '啟動引擎', assembling: '封裝影片', saving: '儲存檔案', completed: '完成' },
    },
    en: {
        title: 'Download plan', intro: 'Default: best video + best audio, producing one finished file. Subtitles and cover are opt-in.', videoQuality: 'Video', audioQuality: 'Audio', best: 'Best available', includeAudio: 'Merge audio', includeSubtitle: 'Embed subtitles', subtitleTrack: 'Subtitle track', noSubtitle: 'No subtitles', includeCover: 'Embed cover', coverUnavailable: 'No cover', browserAction: 'Build in browser', cancel: 'Cancel', completed: 'Finished video created', failed: 'Failed to build video', fallback: 'The selected stream was unavailable; an available parsed stream was used instead.', finalOnly: 'Video, audio, subtitle and cover assets are not saved as separate sidecar files.',
        stages: { resolving: 'Resolving media', 'downloading-video': 'Fetching video', 'downloading-audio': 'Fetching audio', 'downloading-subtitle': 'Fetching subtitles', 'downloading-cover': 'Fetching cover', 'loading-ffmpeg': 'Starting engine', assembling: 'Muxing final video', saving: 'Saving file', completed: 'Completed' },
    },
    ja: {
        title: 'ダウンロード設定', intro: '既定は最高画質 + 最高音質の完成動画1本です。字幕とカバーは必要な場合だけ有効にします。', videoQuality: '画質', audioQuality: '音質', best: '最高品質', includeAudio: '音声を結合', includeSubtitle: '字幕を埋め込む', subtitleTrack: '字幕', noSubtitle: '字幕なし', includeCover: 'カバーを埋め込む', coverUnavailable: 'カバーなし', browserAction: 'ブラウザーで生成', cancel: 'キャンセル', completed: '完成動画を生成しました', failed: '動画生成に失敗しました', fallback: '選択したストリームが使えないため利用可能なストリームへ切り替えました。', finalOnly: '動画・音声・字幕・カバーを別ファイルとして保存しません。',
        stages: { resolving: '解析中', 'downloading-video': '動画を取得', 'downloading-audio': '音声を取得', 'downloading-subtitle': '字幕を取得', 'downloading-cover': 'カバーを取得', 'loading-ffmpeg': 'エンジン起動', assembling: '動画を生成', saving: '保存中', completed: '完了' },
    },
    es: {
        title: 'Plan de descarga', intro: 'Predeterminado: mejor vídeo + mejor audio en un único archivo final. Subtítulos y portada son opcionales.', videoQuality: 'Vídeo', audioQuality: 'Audio', best: 'Mejor disponible', includeAudio: 'Combinar audio', includeSubtitle: 'Integrar subtítulos', subtitleTrack: 'Subtítulos', noSubtitle: 'Sin subtítulos', includeCover: 'Integrar portada', coverUnavailable: 'Sin portada', browserAction: 'Crear en el navegador', cancel: 'Cancelar', completed: 'Vídeo final creado', failed: 'No se pudo crear el vídeo', fallback: 'El flujo seleccionado no estaba disponible; se usó otro disponible.', finalOnly: 'No se guardan vídeo, audio, subtítulos ni portada como archivos separados.',
        stages: { resolving: 'Resolviendo', 'downloading-video': 'Obteniendo vídeo', 'downloading-audio': 'Obteniendo audio', 'downloading-subtitle': 'Obteniendo subtítulos', 'downloading-cover': 'Obteniendo portada', 'loading-ffmpeg': 'Iniciando motor', assembling: 'Creando vídeo', saving: 'Guardando', completed: 'Completado' },
    },
    ru: {
        title: 'План загрузки', intro: 'По умолчанию: лучшее видео + лучший звук в одном итоговом файле. Субтитры и обложка включаются отдельно.', videoQuality: 'Видео', audioQuality: 'Аудио', best: 'Лучшее доступное', includeAudio: 'Объединить аудио', includeSubtitle: 'Встроить субтитры', subtitleTrack: 'Субтитры', noSubtitle: 'Нет субтитров', includeCover: 'Встроить обложку', coverUnavailable: 'Нет обложки', browserAction: 'Собрать в браузере', cancel: 'Отмена', completed: 'Итоговое видео создано', failed: 'Не удалось создать видео', fallback: 'Выбранный поток недоступен; использован доступный поток.', finalOnly: 'Видео, аудио, субтитры и обложка не сохраняются отдельными файлами.',
        stages: { resolving: 'Разбор', 'downloading-video': 'Загрузка видео', 'downloading-audio': 'Загрузка аудио', 'downloading-subtitle': 'Загрузка субтитров', 'downloading-cover': 'Загрузка обложки', 'loading-ffmpeg': 'Запуск движка', assembling: 'Сборка видео', saving: 'Сохранение', completed: 'Готово' },
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

function qualityLabel(option?: QualityChoice | null): string {
    if (!option) return '—';
    return [option.label || option.quality, option.filesize ? formatBytes(option.filesize) : null]
        .filter(Boolean)
        .join(' · ');
}

function CompactToggle({
    checked,
    disabled,
    label,
    onChange,
}: {
    checked: boolean;
    disabled?: boolean;
    label: string;
    onChange: (value: boolean) => void;
}) {
    return (
        <label className={`flex min-h-9 items-center gap-2 rounded-lg px-2.5 text-xs transition-colors ${disabled ? 'cursor-not-allowed opacity-45' : 'cursor-pointer hover:bg-muted'}`}>
            <input
                type="checkbox"
                checked={checked}
                disabled={disabled}
                onChange={(event) => onChange(event.target.checked)}
                className="h-3.5 w-3.5 accent-foreground"
            />
            <span>{label}</span>
        </label>
    );
}

export function AdvancedDownloadOptions({ result }: { result: ResultData }) {
    const pathname = usePathname();
    const copy = copyFor(pathname);
    const capabilities = resolveScopedCapabilities(result);
    const qualityOptions = useMemo(() => normalizeQualityOptions(capabilities.qualityOptions), [capabilities.qualityOptions]);
    const parserBest = qualityOptions.find((option) => option.source === 'parser') || null;
    const subtitles = capabilities.subtitles ?? EMPTY_SUBTITLES;
    const firstSubtitleKey = subtitles[0] ? subtitleKey(subtitles[0], 0) : '';
    const sourceUrl = resolveScopedSourceUrl(result);

    const [videoQuality, setVideoQuality] = useState('best');
    const [audioQuality, setAudioQuality] = useState('best');
    const [includeAudio, setIncludeAudio] = useState(true);
    // Keep the default output exactly what the user asked for: one best video
    // + one best audio. Optional assets must be explicit opt-ins.
    const [includeSubtitle, setIncludeSubtitle] = useState(false);
    const [subtitleId, setSubtitleId] = useState(firstSubtitleKey);
    const [includeCover, setIncludeCover] = useState(false);
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
        if (effectiveVideoQuality?.downloadUrl) return { url: effectiveVideoQuality.downloadUrl, usedFallback: false };
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
            const requestUrl = buildSourceMediaDownloadUrl({ sourceUrl, type: 'audio', quality: audioQuality });
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
            const [video, audio] = await Promise.all([resolveVideoUrl(), resolveAudioUrl()]);
            if (video.usedFallback || audio.usedFallback) toast.message(copy.fallback);
            await createFinalMediaFile({
                title: sanitizeFilename(result.title || 'media'),
                videoUrl: video.url,
                audioUrl: audio.url,
                subtitleUrl: includeSubtitle && selectedSubtitle ? resolveSubtitleUrl(selectedSubtitle) : null,
                subtitleLanguage: selectedSubtitle?.language || null,
                subtitleFormat: selectedSubtitle?.format || null,
                coverUrl: includeCover ? capabilities.cover || null : null,
                sourceUrl,
                signal: controller.signal,
                onProgress: setProgress,
            });
            toast.success(copy.completed);
        } catch (error) {
            if (error instanceof DOMException && error.name === 'AbortError') return;
            console.error('Final media export failed:', error);
            toast.error(copy.failed, { description: error instanceof Error ? error.message : String(error) });
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

    const selectedAudioLabel = AUDIO_QUALITY_PRESETS.find((item) => item.quality === audioQuality)?.label || audioQuality;
    const localEnginePlan = {
        videoSelection: effectiveVideoQuality
            ? { quality: effectiveVideoQuality.quality, label: effectiveVideoQuality.label, height: effectiveVideoQuality.height }
            : null,
        audioQuality,
        includeAudio,
        includeSubtitle: includeSubtitle && Boolean(selectedSubtitle),
        subtitleLanguage: selectedSubtitle?.language || null,
        includeCover: includeCover && Boolean(capabilities.cover),
    };
    const planSummary = [
        qualityLabel(effectiveVideoQuality || qualityOptions[0]),
        includeAudio ? selectedAudioLabel : null,
        includeSubtitle && selectedSubtitle ? getSubtitleDisplayName(selectedSubtitle) : null,
        includeCover && capabilities.cover ? copy.includeCover : null,
    ].filter(Boolean).join(' · ');

    return (
        <section className="min-w-0 space-y-3">
            <div className="flex items-start gap-2.5">
                <PackageCheck className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                <div className="min-w-0">
                    <h3 className="text-sm font-semibold">{copy.title}</h3>
                    <p className="mt-0.5 text-[11px] leading-4 text-muted-foreground">{copy.intro}</p>
                </div>
            </div>

            <div className="grid gap-2 sm:grid-cols-2">
                <div className="space-y-1.5">
                    <div className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
                        <Video className="h-3.5 w-3.5" aria-hidden="true" />{copy.videoQuality}
                    </div>
                    <Select value={videoQuality} onValueChange={setVideoQuality} disabled={running}>
                        <SelectTrigger className="h-9 bg-background text-xs"><SelectValue placeholder={copy.best} /></SelectTrigger>
                        <SelectContent>
                            {qualityOptions.map((option) => <SelectItem key={option.quality} value={option.quality}>{qualityLabel(option)}</SelectItem>)}
                        </SelectContent>
                    </Select>
                </div>
                <div className="space-y-1.5">
                    <div className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
                        <Music className="h-3.5 w-3.5" aria-hidden="true" />{copy.audioQuality}
                    </div>
                    <Select value={audioQuality} onValueChange={setAudioQuality} disabled={running || !includeAudio}>
                        <SelectTrigger className="h-9 bg-background text-xs"><SelectValue placeholder={copy.best} /></SelectTrigger>
                        <SelectContent>
                            {AUDIO_QUALITY_PRESETS.map((option) => <SelectItem key={option.quality} value={option.quality}>{option.label}</SelectItem>)}
                        </SelectContent>
                    </Select>
                </div>
            </div>

            <div className="grid gap-1 rounded-xl bg-muted/25 p-1 sm:grid-cols-3">
                <CompactToggle checked={includeAudio} disabled={running} onChange={setIncludeAudio} label={copy.includeAudio} />
                <CompactToggle checked={includeSubtitle && subtitles.length > 0} disabled={running || subtitles.length === 0} onChange={setIncludeSubtitle} label={subtitles.length ? copy.includeSubtitle : copy.noSubtitle} />
                <CompactToggle checked={includeCover && Boolean(capabilities.cover)} disabled={running || !capabilities.cover} onChange={setIncludeCover} label={capabilities.cover ? copy.includeCover : copy.coverUnavailable} />
            </div>

            {includeSubtitle && subtitles.length > 0 ? (
                <div className="flex items-center gap-2">
                    <Captions className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
                    <Select value={effectiveSubtitleId} onValueChange={setSubtitleId} disabled={running}>
                        <SelectTrigger className="h-9 min-w-0 flex-1 bg-background text-xs"><SelectValue /></SelectTrigger>
                        <SelectContent>
                            {subtitles.map((track, index) => (
                                <SelectItem key={subtitleKey(track, index)} value={subtitleKey(track, index)}>
                                    {getSubtitleDisplayName(track)}{track.format ? ` · ${track.format.toUpperCase()}` : ''}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </div>
            ) : null}

            <div className="rounded-lg px-2.5 py-2 text-[11px] leading-4 text-muted-foreground ring-1 ring-border/60">
                <span className="font-medium text-foreground">{planSummary}</span>
                <span className="mx-1.5">·</span>{copy.finalOnly}
            </div>

            <LocalEngineDownloadCard result={result} plan={localEnginePlan} disabled={running} />

            {progress ? (
                <div className="space-y-2 rounded-xl bg-muted/20 p-2.5" role="status" aria-live="polite">
                    <div className="flex items-center justify-between gap-3 text-xs">
                        <span className="flex min-w-0 items-center gap-1.5 font-medium">
                            {running ? <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" aria-hidden="true" /> : <Check className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />}
                            <span className="truncate">{copy.stages[progress.stage]}</span>
                        </span>
                        <span className="tabular-nums text-muted-foreground">{Math.round(progress.progress)}%</span>
                    </div>
                    <Progress value={progress.progress} className="h-1.5" />
                    {progress.loaded && progress.total ? <div className="text-[10px] tabular-nums text-muted-foreground">{formatBytes(progress.loaded)} / {formatBytes(progress.total)}</div> : null}
                </div>
            ) : null}

            {running ? (
                <Button type="button" variant="destructive" className="min-h-10 w-full transition-transform duration-150 active:scale-[0.98]" onClick={cancel}>
                    <X className="h-4 w-4" aria-hidden="true" />{copy.cancel}
                </Button>
            ) : (
                <Button type="button" variant="outline" className="min-h-10 w-full transition-transform duration-150 active:scale-[0.98]" onClick={startFinalExport}>
                    <PackageCheck className="h-4 w-4" aria-hidden="true" />{copy.browserAction}
                </Button>
            )}
        </section>
    );
}
