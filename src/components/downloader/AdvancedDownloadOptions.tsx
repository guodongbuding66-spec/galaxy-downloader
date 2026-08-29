'use client';

import { useMemo, useState } from 'react';
import { usePathname } from 'next/navigation';
import {
    Captions,
    Clipboard,
    Download,
    FileJson,
    Image as ImageIcon,
    Music,
    SlidersHorizontal,
    Video,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
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
    createMediaMetadata,
    getSubtitleDisplayName,
    inferExtension,
    normalizeQualityOptions,
    resolveSubtitleUrl,
} from '@/lib/media-download-options';
import type { SubtitleTrack, UnifiedParseResult, VideoQualityOption } from '@/lib/types';
import { downloadFile, formatBytes, sanitizeFilename } from '@/lib/utils';

type ResultData = NonNullable<UnifiedParseResult['data']>;

const EMPTY_SUBTITLES: SubtitleTrack[] = [];

type Copy = {
    title: string;
    quality: string;
    qualityHint: string;
    parserFormats: string;
    genericPresets: string;
    downloadVideo: string;
    audioQuality: string;
    downloadAudio: string;
    extras: string;
    cover: string;
    subtitles: string;
    noSubtitles: string;
    metadata: string;
    copySource: string;
    copied: string;
    best: string;
};

const COPY: Record<string, Copy> = {
    zh: {
        title: '高级下载选项',
        quality: '视频清晰度',
        qualityHint: '按所选清晰度重新向解析后端请求媒体，不再复用可能偏低清晰度的临时 CDN 流。若平台没有该档位，后端应回退到最接近或最佳可用画质。',
        parserFormats: '解析器返回的可用格式',
        genericPresets: '通用画质预设',
        downloadVideo: '下载所选画质',
        audioQuality: '音频质量',
        downloadAudio: '下载所选音质',
        extras: '附加资源',
        cover: '下载封面',
        subtitles: '下载字幕',
        noSubtitles: '当前解析结果未返回可下载的字幕轨道',
        metadata: '下载媒体信息 JSON',
        copySource: '复制原始链接',
        copied: '原始链接已复制',
        best: '最佳可用',
    },
    'zh-tw': {
        title: '進階下載選項',
        quality: '影片畫質',
        qualityHint: '依所選畫質重新向解析後端請求媒體，不再重複使用可能偏低畫質的臨時 CDN 串流。若平台沒有該畫質，後端應回退至最接近或最佳可用畫質。',
        parserFormats: '解析器回傳的可用格式',
        genericPresets: '通用畫質預設',
        downloadVideo: '下載所選畫質',
        audioQuality: '音訊品質',
        downloadAudio: '下載所選音質',
        extras: '附加資源',
        cover: '下載封面',
        subtitles: '下載字幕',
        noSubtitles: '目前解析結果未回傳可下載的字幕軌道',
        metadata: '下載媒體資訊 JSON',
        copySource: '複製原始連結',
        copied: '原始連結已複製',
        best: '最佳可用',
    },
    en: {
        title: 'Advanced download options',
        quality: 'Video quality',
        qualityHint: 'Requests a fresh stream for the selected quality instead of reusing a possibly low-resolution temporary CDN URL. If unavailable, the backend should fall back to the nearest/best quality.',
        parserFormats: 'Formats reported by parser',
        genericPresets: 'Generic quality presets',
        downloadVideo: 'Download selected quality',
        audioQuality: 'Audio quality',
        downloadAudio: 'Download selected audio',
        extras: 'Extra resources',
        cover: 'Download cover',
        subtitles: 'Download subtitles',
        noSubtitles: 'No downloadable subtitle tracks were returned by the parser',
        metadata: 'Download media info JSON',
        copySource: 'Copy source URL',
        copied: 'Source URL copied',
        best: 'Best available',
    },
    ja: {
        title: '詳細ダウンロード設定',
        quality: '動画画質',
        qualityHint: '低画質の一時 CDN URL を再利用せず、選択した画質で解析バックエンドへ再リクエストします。利用できない場合は最も近い／最良の画質へフォールバックします。',
        parserFormats: '解析結果の利用可能フォーマット',
        genericPresets: '共通画質プリセット',
        downloadVideo: '選択画質でダウンロード',
        audioQuality: '音声品質',
        downloadAudio: '選択音質でダウンロード',
        extras: '追加リソース',
        cover: 'サムネイルを保存',
        subtitles: '字幕を保存',
        noSubtitles: '解析結果にダウンロード可能な字幕トラックがありません',
        metadata: 'メディア情報 JSON を保存',
        copySource: '元 URL をコピー',
        copied: '元 URL をコピーしました',
        best: '最高品質',
    },
    es: {
        title: 'Opciones avanzadas de descarga',
        quality: 'Calidad de vídeo',
        qualityHint: 'Solicita un flujo nuevo con la calidad elegida en vez de reutilizar una URL CDN temporal de baja resolución. Si no existe, el servidor usará la calidad más cercana o la mejor disponible.',
        parserFormats: 'Formatos informados por el analizador',
        genericPresets: 'Preajustes genéricos',
        downloadVideo: 'Descargar calidad elegida',
        audioQuality: 'Calidad de audio',
        downloadAudio: 'Descargar audio elegido',
        extras: 'Recursos adicionales',
        cover: 'Descargar portada',
        subtitles: 'Descargar subtítulos',
        noSubtitles: 'El analizador no devolvió pistas de subtítulos descargables',
        metadata: 'Descargar información JSON',
        copySource: 'Copiar URL original',
        copied: 'URL original copiada',
        best: 'Mejor disponible',
    },
    ru: {
        title: 'Расширенные параметры загрузки',
        quality: 'Качество видео',
        qualityHint: 'Запрашивает новый поток выбранного качества вместо временной CDN-ссылки низкого разрешения. Если качество недоступно, сервер выберет ближайшее или лучшее доступное.',
        parserFormats: 'Форматы от парсера',
        genericPresets: 'Универсальные пресеты',
        downloadVideo: 'Скачать выбранное качество',
        audioQuality: 'Качество аудио',
        downloadAudio: 'Скачать выбранное аудио',
        extras: 'Дополнительные ресурсы',
        cover: 'Скачать обложку',
        subtitles: 'Скачать субтитры',
        noSubtitles: 'Парсер не вернул доступных дорожек субтитров',
        metadata: 'Скачать сведения JSON',
        copySource: 'Копировать исходную ссылку',
        copied: 'Исходная ссылка скопирована',
        best: 'Лучшее доступное',
    },
};

function resolveCopy(pathname: string | null): Copy {
    const locale = pathname?.split('/').filter(Boolean)[0] || 'en';
    return COPY[locale] || COPY.en;
}

function saveJsonFile(filename: string, value: unknown) {
    const blob = new Blob([JSON.stringify(value, null, 2)], { type: 'application/json;charset=utf-8' });
    const objectUrl = URL.createObjectURL(blob);
    downloadFile(objectUrl, filename);
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 10_000);
}

function resolveScopedCapabilities(result: ResultData): {
    qualityOptions?: VideoQualityOption[];
    subtitles?: SubtitleTrack[];
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

export function AdvancedDownloadOptions({ result }: { result: ResultData }) {
    const pathname = usePathname();
    const copy = resolveCopy(pathname);
    const capabilities = resolveScopedCapabilities(result);
    const qualityOptions = useMemo(
        () => normalizeQualityOptions(capabilities.qualityOptions),
        [capabilities.qualityOptions]
    );
    const parserProvidedFormats = Boolean(capabilities.qualityOptions?.length);
    const subtitles = capabilities.subtitles ?? EMPTY_SUBTITLES;
    const [videoQuality, setVideoQuality] = useState('best');
    const [audioQuality, setAudioQuality] = useState('best');
    const [subtitleId, setSubtitleId] = useState('');
    const sourceUrl = resolveScopedSourceUrl(result);
    const safeTitle = sanitizeFilename(result.title || 'media').slice(0, 120) || 'media';
    const showVideoControls = result.kind !== 'audio'
        && result.noteType !== 'audio'
        && result.noteType !== 'image'
        && result.videoAudioMode !== 'pure_music';
    const showAudioControls = result.noteType !== 'image';

    const selectedQuality = qualityOptions.find((option) => option.quality === videoQuality) || qualityOptions[0];
    const firstSubtitleId = subtitles[0]
        ? subtitles[0].id || `${subtitles[0].language}-0`
        : '';
    const effectiveSubtitleId = subtitles.some(
        (track, index) => (track.id || `${track.language}-${index}`) === subtitleId
    ) ? subtitleId : firstSubtitleId;

    const handleVideoDownload = () => {
        if (!sourceUrl || !selectedQuality) return;
        const url = selectedQuality.downloadUrl || buildSourceMediaDownloadUrl({
            sourceUrl,
            type: 'video',
            quality: selectedQuality.quality,
            formatId: selectedQuality.formatId,
        });
        downloadFile(url);
    };

    const handleAudioDownload = () => {
        if (!sourceUrl) return;
        downloadFile(buildSourceMediaDownloadUrl({
            sourceUrl,
            type: 'audio',
            quality: audioQuality,
        }));
    };

    const handleCoverDownload = () => {
        if (!result.cover) return;
        const extension = inferExtension(result.cover, 'jpg');
        downloadFile(result.cover, `${safeTitle}-cover.${extension}`);
    };

    const handleSubtitleDownload = () => {
        const index = subtitles.findIndex(
            (track, trackIndex) => (track.id || `${track.language}-${trackIndex}`) === effectiveSubtitleId
        );
        if (index < 0) return;
        const track = subtitles[index];
        const url = resolveSubtitleUrl(track);
        if (!url) return;
        const extension = track.format || inferExtension(url, 'vtt');
        const language = sanitizeFilename(track.language || `subtitle-${index + 1}`);
        downloadFile(url, `${safeTitle}-${language}.${extension}`);
    };

    const handleMetadataDownload = () => {
        saveJsonFile(`${safeTitle}-info.json`, createMediaMetadata({
            ...result,
            url: sourceUrl,
            qualityOptions: capabilities.qualityOptions,
            subtitles: capabilities.subtitles,
        }));
    };

    const handleCopySource = async () => {
        if (!sourceUrl) return;
        try {
            await navigator.clipboard.writeText(sourceUrl);
        } catch {
            const input = document.createElement('textarea');
            input.value = sourceUrl;
            input.style.position = 'fixed';
            input.style.opacity = '0';
            document.body.appendChild(input);
            input.select();
            document.execCommand('copy');
            document.body.removeChild(input);
        }
        toast.success(copy.copied);
    };

    if (!sourceUrl) return null;

    return (
        <div className="space-y-3 rounded-lg border border-border/80 bg-muted/20 p-3">
            <div className="flex items-center gap-2">
                <SlidersHorizontal className="h-4 w-4" />
                <div className="text-sm font-medium">{copy.title}</div>
            </div>

            {(showVideoControls || showAudioControls) && (
                <div className={`grid gap-3 ${showVideoControls && showAudioControls ? 'lg:grid-cols-2' : ''}`}>
                    {showVideoControls && (
                        <div className="space-y-2 rounded-md border bg-background/70 p-2.5">
                            <div className="flex items-center justify-between gap-2">
                                <div className="flex items-center gap-1.5 text-xs font-medium">
                                    <Video className="h-3.5 w-3.5" />
                                    {copy.quality}
                                </div>
                                <span className="text-[10px] text-muted-foreground">
                                    {parserProvidedFormats ? copy.parserFormats : copy.genericPresets}
                                </span>
                            </div>
                            <Select value={selectedQuality?.quality || 'best'} onValueChange={setVideoQuality}>
                                <SelectTrigger className="h-9">
                                    <SelectValue placeholder={copy.best} />
                                </SelectTrigger>
                                <SelectContent>
                                    {qualityOptions.map((option) => {
                                        const details = [
                                            option.label || option.quality,
                                            option.filesize ? formatBytes(option.filesize) : null,
                                        ].filter(Boolean).join(' · ');
                                        return (
                                            <SelectItem key={option.quality} value={option.quality}>
                                                {details}
                                            </SelectItem>
                                        );
                                    })}
                                </SelectContent>
                            </Select>
                            <Button type="button" className="w-full" onClick={handleVideoDownload}>
                                <Download className="h-4 w-4" />
                                {copy.downloadVideo}
                            </Button>
                            <p className="text-[11px] leading-relaxed text-muted-foreground">
                                {copy.qualityHint}
                            </p>
                        </div>
                    )}

                    {showAudioControls && (
                        <div className="space-y-2 rounded-md border bg-background/70 p-2.5">
                            <div className="flex items-center gap-1.5 text-xs font-medium">
                                <Music className="h-3.5 w-3.5" />
                                {copy.audioQuality}
                            </div>
                            <Select value={audioQuality} onValueChange={setAudioQuality}>
                                <SelectTrigger className="h-9">
                                    <SelectValue placeholder={copy.best} />
                                </SelectTrigger>
                                <SelectContent>
                                    {AUDIO_QUALITY_PRESETS.map((option) => (
                                        <SelectItem key={option.quality} value={option.quality}>
                                            {option.quality === 'best' ? copy.best : option.label}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                            <Button
                                type="button"
                                variant="secondary"
                                className="w-full"
                                onClick={handleAudioDownload}
                            >
                                <Download className="h-4 w-4" />
                                {copy.downloadAudio}
                            </Button>
                        </div>
                    )}
                </div>
            )}

            <div className="space-y-2">
                <div className="text-xs font-medium">{copy.extras}</div>
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                    <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={!result.cover}
                        onClick={handleCoverDownload}
                    >
                        <ImageIcon className="h-4 w-4" aria-hidden="true" />
                        {copy.cover}
                    </Button>

                    {subtitles.length > 0 ? (
                        <div className="flex min-w-0 gap-1">
                            <Select value={effectiveSubtitleId} onValueChange={setSubtitleId}>
                                <SelectTrigger className="h-8 min-w-0 flex-1 text-xs">
                                    <SelectValue placeholder={copy.subtitles} />
                                </SelectTrigger>
                                <SelectContent>
                                    {subtitles.map((track, index) => {
                                        const value = track.id || `${track.language}-${index}`;
                                        return (
                                            <SelectItem
                                                key={value}
                                                value={value}
                                                disabled={!resolveSubtitleUrl(track)}
                                            >
                                                {getSubtitleDisplayName(track)}
                                            </SelectItem>
                                        );
                                    })}
                                </SelectContent>
                            </Select>
                            <Button
                                type="button"
                                variant="outline"
                                size="icon"
                                className="h-8 w-8 shrink-0"
                                onClick={handleSubtitleDownload}
                            >
                                <Captions className="h-4 w-4" />
                                <span className="sr-only">{copy.subtitles}</span>
                            </Button>
                        </div>
                    ) : (
                        <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            disabled
                            title={copy.noSubtitles}
                        >
                            <Captions className="h-4 w-4" />
                            {copy.subtitles}
                        </Button>
                    )}

                    <Button type="button" variant="outline" size="sm" onClick={handleMetadataDownload}>
                        <FileJson className="h-4 w-4" />
                        {copy.metadata}
                    </Button>

                    <Button type="button" variant="outline" size="sm" onClick={() => void handleCopySource()}>
                        <Clipboard className="h-4 w-4" />
                        {copy.copySource}
                    </Button>
                </div>
                {subtitles.length === 0 && (
                    <p className="text-[11px] text-muted-foreground">{copy.noSubtitles}</p>
                )}
            </div>
        </div>
    );
}
