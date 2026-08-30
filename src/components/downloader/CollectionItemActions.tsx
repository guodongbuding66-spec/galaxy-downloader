import { Headphones, Play } from 'lucide-react';

import { useDictionary } from '@/i18n/client';

import { AudioDownloadIcon, VideoDownloadIcon } from './CustomIcons';
import { MediaActionIconButton } from './MediaActionIconButton';
import { hasSourceUrl, shouldShowVideoDownloadButton } from './result-card-visibility';

export type CollectionPreviewMediaType = 'video' | 'audio';

interface CollectionItemActionsProps {
    title: string;
    canPlayVideo: boolean;
    canPlayAudio: boolean;
    videoDownloadUrl?: string | null;
    audioDownloadUrl?: string | null;
    videoLoading: boolean;
    audioLoading: boolean;
    onPlay: (mediaType: CollectionPreviewMediaType) => void;
    onDownloadVideo: (url: string) => void;
    onDownloadAudio: (url: string) => void;
}

function getActionRowClass(actionCount: number) {
    return actionCount === 2 ? 'grid-cols-1 sm:grid-cols-2' : 'grid-cols-1';
}

export function CollectionItemActions({
    title,
    canPlayVideo,
    canPlayAudio,
    videoDownloadUrl,
    audioDownloadUrl,
    videoLoading,
    audioLoading,
    onPlay,
    onDownloadVideo,
    onDownloadAudio,
}: CollectionItemActionsProps) {
    const dict = useDictionary();
    const canDownloadVideo = shouldShowVideoDownloadButton(videoDownloadUrl);
    const canDownloadAudio = hasSourceUrl(audioDownloadUrl);
    const previewActionCount = Number(canPlayVideo) + Number(canPlayAudio);
    const downloadActionCount = Number(canDownloadVideo) + Number(canDownloadAudio);

    return (
        <div className="w-full space-y-2 md:min-w-[13rem] md:shrink-0">
            {previewActionCount > 0 && (
                <div className={`grid ${getActionRowClass(previewActionCount)} gap-2`}>
                    {canPlayVideo && (
                        <MediaActionIconButton
                            label={`${dict.result.playVideo}: ${title}`}
                            text={dict.result.playVideo}
                            icon={Play}
                            variant="secondary"
                            size="sm"
                            className="min-h-10 w-full"
                            onClick={() => onPlay('video')}
                        />
                    )}
                    {canPlayAudio && (
                        <MediaActionIconButton
                            label={`${dict.result.playAudio}: ${title}`}
                            text={dict.result.playAudio}
                            icon={Headphones}
                            variant="secondary"
                            size="sm"
                            className="min-h-10 w-full"
                            onClick={() => onPlay('audio')}
                        />
                    )}
                </div>
            )}
            {downloadActionCount > 0 && (
                <div className={`grid ${getActionRowClass(downloadActionCount)} gap-2`}>
                    {canDownloadVideo && (
                        <MediaActionIconButton
                            label={`${dict.result.downloadVideo}: ${title}`}
                            text={dict.result.downloadVideo}
                            icon={VideoDownloadIcon}
                            variant="default"
                            size="sm"
                            className="min-h-10 w-full"
                            disabled={videoLoading}
                            loading={videoLoading}
                            onClick={() => onDownloadVideo(videoDownloadUrl!)}
                        />
                    )}
                    {canDownloadAudio && (
                        <MediaActionIconButton
                            label={`${dict.result.downloadAudio}: ${title}`}
                            text={dict.result.downloadAudio}
                            icon={AudioDownloadIcon}
                            variant="default"
                            size="sm"
                            className="min-h-10 w-full"
                            disabled={audioLoading}
                            loading={audioLoading}
                            onClick={() => onDownloadAudio(audioDownloadUrl!)}
                        />
                    )}
                </div>
            )}
        </div>
    );
}
