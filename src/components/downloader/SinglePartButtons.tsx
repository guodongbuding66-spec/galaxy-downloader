import { Download, Headphones, MonitorPlay } from 'lucide-react';

import type { AudioExtractTask } from '@/components/audio-tool/types';
import type { HlsDownloadDialogRequest } from '@/components/hls-download-dialog';
import type { MediaPreviewRequest } from '@/components/downloader/media-preview';
import { useDictionary } from '@/i18n/client';
import { isHlsPlaylistUrl } from '@/lib/hls-playback';
import type { UnifiedParseResult } from '@/lib/types';
import { getProxiedDownloadUrl } from '@/lib/utils';

import { AdvancedDownloadOptions } from './AdvancedDownloadOptions';
import { MediaActionIconButton } from './MediaActionIconButton';
import { canPreviewResultAudio, canPreviewResultVideo } from './media-preview';
import { getResultMediaActions } from './result-card-visibility';
import { AudioDownloadIcon } from './CustomIcons';

function getActionRowClass(actionCount: number) {
    return actionCount >= 2 ? 'grid-cols-1 sm:grid-cols-2' : 'grid-cols-1';
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

    const isAudioOnly = result.kind === 'audio'
        || result.noteType === 'audio'
        || result.videoAudioMode === 'pure_music';
    const isImageWithAudio = result.noteType === 'image' && Boolean(rawAudioDownloadUrl);
    const showStandaloneAudioAction = isAudioOnly || isImageWithAudio;
    const isVideoResult = !isAudioOnly && result.noteType !== 'image';
    const showVideoPreview = isVideoResult && previewSourceUrl.length > 0 && canPreviewResultVideo(result);
    const showAudioPreview = previewSourceUrl.length > 0 && canPreviewResultAudio(result);
    const showBrowserHlsDownload = isVideoResult && (
        videoAction === 'browser-hls-download'
        || (videoAction === 'hide' && isHlsPlaylistUrl(result.originDownloadVideoUrl))
    );
    const previewActionCount = Number(showVideoPreview) + Number(showAudioPreview);
    const previewTitle = result.title || result.desc || 'Media';

    const openBrowserHlsDownload = () => {
        const workerPlaylistUrl = result.downloadVideoUrl;
        if (!workerPlaylistUrl) return;
        onOpenHlsDownload({
            sourceUrl: result.url || result.originDownloadVideoUrl || workerPlaylistUrl,
            resolvedPlaylistUrl: workerPlaylistUrl,
            title: result.title || result.desc || 'Media',
        });
    };

    const handleStandaloneAudioAction = () => {
        if (audioAction === 'extract-audio' && rawVideoDownloadUrl) {
            onOpenExtractAudio({
                action: 'extract-audio',
                title: result.title || result.desc || undefined,
                sourceUrl: result.url || null,
                videoUrl: getProxiedDownloadUrl(rawVideoDownloadUrl),
                audioUrl: rawAudioDownloadUrl ? getProxiedDownloadUrl(rawAudioDownloadUrl) : null,
                mediaActions: result.mediaActions,
            });
            return;
        }

        if (rawAudioDownloadUrl) {
            const anchor = document.createElement('a');
            anchor.href = getProxiedDownloadUrl(rawAudioDownloadUrl);
            anchor.download = '';
            anchor.style.display = 'none';
            document.body.appendChild(anchor);
            anchor.click();
            anchor.remove();
        }
    };

    return (
        <div className="space-y-4">
            {previewActionCount > 0 && (
                <div className={`grid ${getActionRowClass(previewActionCount)} gap-2`}>
                    {showVideoPreview && (
                        <MediaActionIconButton
                            label={dict.result.playVideo}
                            icon={MonitorPlay}
                            variant="secondary"
                            className="min-h-10 w-full min-w-0"
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
                            className="min-h-10 w-full min-w-0"
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

            {showBrowserHlsDownload && (
                <MediaActionIconButton
                    label={dict.result.browserDownloadVideo}
                    icon={Download}
                    variant="outline"
                    className="min-h-10 w-full min-w-0"
                    onClick={openBrowserHlsDownload}
                />
            )}

            {showStandaloneAudioAction && audioAction !== 'hide' && (
                <MediaActionIconButton
                    label={audioAction === 'extract-audio' ? dict.extractAudio.button : dict.result.downloadAudio}
                    icon={AudioDownloadIcon}
                    variant="default"
                    className="min-h-10 w-full min-w-0"
                    onClick={handleStandaloneAudioAction}
                />
            )}

            {isVideoResult && <AdvancedDownloadOptions result={result} />}
        </div>
    );
}
