import { useState } from 'react';
import { Download, ExternalLink, MonitorPlay, Headphones } from 'lucide-react';

import type { AudioExtractTask } from '@/components/audio-tool/types';
import type { HlsDownloadDialogRequest } from '@/components/hls-download-dialog';
import type { MediaPreviewRequest } from '@/components/downloader/media-preview';
import { Button } from '@/components/ui/button';
import { useDictionary } from '@/i18n/client';
import { isHlsPlaylistUrl } from '@/lib/hls-playback';
import { buildSourceMediaDownloadUrl } from '@/lib/media-download-options';
import type { UnifiedParseResult } from '@/lib/types';
import { downloadFile, getProxiedDownloadUrl } from '@/lib/utils';

import { AdvancedDownloadOptions } from './AdvancedDownloadOptions';
import { MediaActionIconButton } from './MediaActionIconButton';
import { canPreviewResultAudio, canPreviewResultVideo } from './media-preview';
import { getResultMediaActions } from './result-card-visibility';
import { VideoDownloadIcon, AudioDownloadIcon } from './CustomIcons';

function getActionRowClass(actionCount: number) {
    if (actionCount >= 4) {
        return 'grid-cols-4';
    }

    if (actionCount === 3) {
        return 'grid-cols-3';
    }

    if (actionCount === 2) {
        return 'grid-cols-2';
    }

    return 'grid-cols-1';
}

export function SinglePartButtons({
    result,
    previewItem,
    onOpenExtractAudio,
    onOpenHlsDownload,
    onRequestPreview,
}: {
    result: NonNullable<UnifiedParseResult['data']>;
    previewItem?: string;
    onOpenExtractAudio: (task: AudioExtractTask) => void;
    onOpenHlsDownload: (request: HlsDownloadDialogRequest) => void;
    onRequestPreview: (request: MediaPreviewRequest) => void;
}) {
    const dict = useDictionary();
    const [videoLoading, setVideoLoading] = useState(false);
    const [audioLoading, setAudioLoading] = useState(false);
    const previewSourceUrl = typeof result.url === 'string' ? result.url.trim() : '';
    const rawVideoDownloadUrl = result.downloadVideoUrl || result.originDownloadVideoUrl;
    const rawAudioDownloadUrl = result.downloadAudioUrl || result.originDownloadAudioUrl || null;
    const { videoAction, audioAction } = getResultMediaActions({
        videoAudioMode: result.videoAudioMode,
        mediaActions: result.mediaActions,
        videoDownloadUrl: rawVideoDownloadUrl,
        audioDownloadUrl: rawAudioDownloadUrl,
        originDownloadVideoUrl: result.originDownloadVideoUrl,
        originDownloadAudioUrl: result.originDownloadAudioUrl,
    });
    const videoDownloadUrl = rawVideoDownloadUrl
        ? getProxiedDownloadUrl(rawVideoDownloadUrl)
        : null;
    const audioDownloadUrl = rawAudioDownloadUrl
        ? getProxiedDownloadUrl(rawAudioDownloadUrl)
        : null;
    const bestVideoDownloadUrl = previewSourceUrl
        ? buildSourceMediaDownloadUrl({ sourceUrl: previewSourceUrl, type: 'video', quality: 'best' })
        : videoDownloadUrl;
    const bestAudioDownloadUrl = previewSourceUrl
        ? buildSourceMediaDownloadUrl({ sourceUrl: previewSourceUrl, type: 'audio', quality: 'best' })
        : audioDownloadUrl;
    const showVideoDownload = videoAction === 'direct-download' || videoAction === 'merge-then-download';
    const showBrowserHlsDownload = videoAction === 'browser-hls-download' || (videoAction === 'hide' && isHlsPlaylistUrl(result.originDownloadVideoUrl));
    const showAudioDownload = audioAction !== 'hide';
    const showVideoPreview = previewSourceUrl.length > 0 && canPreviewResultVideo(result);
    const showAudioPreview = previewSourceUrl.length > 0 && canPreviewResultAudio(result);
    const showOriginVideoLink =
        typeof result.originDownloadVideoUrl === 'string'
        && result.originDownloadVideoUrl.length > 0
        && result.originDownloadVideoUrl !== rawVideoDownloadUrl;
    const showOriginAudioLink =
        typeof result.originDownloadAudioUrl === 'string'
        && result.originDownloadAudioUrl.length > 0
        && result.originDownloadAudioUrl !== rawAudioDownloadUrl;

    const handleDownload = (url: string, setLoading: (value: boolean) => void) => {
        setLoading(true);
        downloadFile(url);
        setTimeout(() => setLoading(false), 1500);
    };

    const openBrowserHlsDownload = () => {
        const workerPlaylistUrl = result.downloadVideoUrl;
        if (!workerPlaylistUrl) {
            return;
        }

        onOpenHlsDownload({
            sourceUrl: result.url || result.originDownloadVideoUrl || workerPlaylistUrl,
            resolvedPlaylistUrl: workerPlaylistUrl,
            title: result.title || result.desc || dict.history.unknownTitle,
        });
    };

    const openResultTask = (action: AudioExtractTask['action']) => {
        onOpenExtractAudio({
            action,
            title: result.title || result.desc || undefined,
            sourceUrl: result.url || null,
            audioUrl: audioDownloadUrl,
            videoUrl: videoDownloadUrl,
            mediaActions: result.mediaActions,
        });
    };
    const previewTitle = result.title || result.desc || dict.result.title;
    const previewActionCount = Number(showVideoPreview) + Number(showAudioPreview);
    const downloadActionCount = Number(showVideoDownload)
        + Number(showBrowserHlsDownload)
        + Number(showAudioDownload);
    const actionButtonClass = 'w-full min-w-0';

    return (
        <>
            <div className="space-y-2">
                {previewActionCount > 0 && (
                    <div className={`grid ${getActionRowClass(previewActionCount)} gap-2`}>
                        {showVideoPreview && (
                            <MediaActionIconButton
                                label={dict.result.playVideo}
                                icon={MonitorPlay}
                                variant="secondary"
                                className={actionButtonClass}
                                onClick={() => onRequestPreview({
                                    mediaType: 'video',
                                    sourceUrl: previewSourceUrl,
                                    title: previewTitle,
                                    item: previewItem,
                                    autoplay: true,
                                })}
                            />
                        )}
                        {showAudioPreview && (
                            <MediaActionIconButton
                                label={dict.result.playAudio}
                                icon={Headphones}
                                variant="secondary"
                                className={actionButtonClass}
                                onClick={() => onRequestPreview({
                                    mediaType: 'audio',
                                    sourceUrl: previewSourceUrl,
                                    title: previewTitle,
                                    item: previewItem,
                                    autoplay: true,
                                })}
                            />
                        )}
                    </div>
                )}
                {downloadActionCount > 0 && (
                    <div className={`grid ${getActionRowClass(downloadActionCount)} gap-2`}>
                        {showVideoDownload && (
                            <MediaActionIconButton
                                label={videoAction === 'merge-then-download'
                                    ? dict.result.mergeDownloadVideo
                                    : dict.result.downloadVideo}
                                icon={VideoDownloadIcon}
                                variant="default"
                                className={actionButtonClass}
                                disabled={videoLoading}
                                loading={videoLoading}
                                onClick={() => {
                                    if (videoAction === 'merge-then-download') {
                                        openResultTask('merge-video');
                                        return;
                                    }

                                    if (bestVideoDownloadUrl) {
                                        handleDownload(bestVideoDownloadUrl, setVideoLoading);
                                    }
                                }}
                            />
                        )}
                        {showBrowserHlsDownload && (
                            <MediaActionIconButton
                                label={dict.result.browserDownloadVideo}
                                icon={Download}
                                variant="outline"
                                className={actionButtonClass}
                                onClick={openBrowserHlsDownload}
                            />
                        )}
                        {showAudioDownload && (
                            <MediaActionIconButton
                                label={audioAction === 'direct-download'
                                    ? dict.result.downloadAudio
                                    : dict.extractAudio.button}
                                icon={AudioDownloadIcon}
                                variant="default"
                                className={actionButtonClass}
                                disabled={audioLoading}
                                loading={audioLoading && audioAction === 'direct-download'}
                                onClick={() => {
                                    if (audioAction === 'extract-audio') {
                                        openResultTask('extract-audio');
                                        return;
                                    }

                                    if (bestAudioDownloadUrl) {
                                        handleDownload(bestAudioDownloadUrl, setAudioLoading);
                                    }
                                }}
                            />
                        )}
                    </div>
                )}
            </div>
            {videoAction === 'merge-then-download' && (
                <p className="text-xs text-muted-foreground">
                    {dict.result.mergeDownloadVideoHint}
                </p>
            )}
            {result.noteType === 'audio' && (
                <p className="text-xs text-muted-foreground">
                    {dict.result.pureMusicHint}
                </p>
            )}
            {(showOriginVideoLink || showOriginAudioLink) && (
                <div className="flex flex-wrap items-center gap-x-1 gap-y-0.5 text-xs text-muted-foreground">
                    {showOriginVideoLink && (
                        <Button variant="link" size="sm" className="h-auto px-0 py-0 text-xs" asChild>
                            <a
                                href={getProxiedDownloadUrl(result.originDownloadVideoUrl!)}
                                target="_blank"
                                rel="noopener noreferrer"
                            >
                                <ExternalLink className="h-3.5 w-3.5" />
                                {dict.result.originDownloadVideo}
                            </a>
                        </Button>
                    )}
                    {showOriginAudioLink && (
                        <Button variant="link" size="sm" className="h-auto px-0 py-0 text-xs" asChild>
                            <a
                                href={getProxiedDownloadUrl(result.originDownloadAudioUrl!)}
                                target="_blank"
                                rel="noopener noreferrer"
                            >
                                <ExternalLink className="h-3.5 w-3.5" />
                                {dict.result.originDownloadAudio}
                            </a>
                        </Button>
                    )}
                </div>
            )}

            <AdvancedDownloadOptions result={result} />
        </>
    );
}
