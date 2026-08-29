import { Download, Headphones, MonitorPlay } from 'lucide-react';

import type { AudioExtractTask } from '@/components/audio-tool/types';
import type { HlsDownloadDialogRequest } from '@/components/hls-download-dialog';
import type { MediaPreviewRequest } from '@/components/downloader/media-preview';
import { isHlsPlaylistUrl } from '@/lib/hls-playback';
import type { UnifiedParseResult } from '@/lib/types';
import { getProxiedDownloadUrl } from '@/lib/utils';

import { AdvancedDownloadOptions } from './AdvancedDownloadOptions';
import { MediaActionIconButton } from './MediaActionIconButton';
import { canPreviewResultAudio, canPreviewResultVideo } from './media-preview';
import { getResultMediaActions } from './result-card-visibility';
import { AudioDownloadIcon } from './CustomIcons';

function getActionRowClass(actionCount: number) {
    if (actionCount >= 3) return 'grid-cols-3';
    if (actionCount === 2) return 'grid-cols-2';
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
    const showVideoPreview = !isAudioOnly && previewSourceUrl.length > 0 && canPreviewResultVideo(result);
    const showAudioPreview = previewSourceUrl.length > 0 && canPreviewResultAudio(result);
    const showBrowserHlsDownload = !isAudioOnly && (
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

    const handleAudioOnlyAction = () => {
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
        <div className="space-y-3">
            {previewActionCount > 0 && (
                <div className={`grid ${getActionRowClass(previewActionCount)} gap-2`}>
                    {showVideoPreview && (
                        <MediaActionIconButton
                            label="播放视频"
                            icon={MonitorPlay}
                            variant="secondary"
                            className="w-full min-w-0"
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
                            label="播放音频"
                            icon={Headphones}
                            variant="secondary"
                            className="w-full min-w-0"
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
                    label="HLS 浏览器下载（兼容模式）"
                    icon={Download}
                    variant="outline"
                    className="w-full min-w-0"
                    onClick={openBrowserHlsDownload}
                />
            )}

            {isAudioOnly && audioAction !== 'hide' && (
                <MediaActionIconButton
                    label={audioAction === 'extract-audio' ? '提取音频' : '下载音频'}
                    icon={AudioDownloadIcon}
                    variant="default"
                    className="w-full min-w-0"
                    onClick={handleAudioOnlyAction}
                />
            )}

            {!isAudioOnly && <AdvancedDownloadOptions result={result} />}
        </div>
    );
}
