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

    return (
        <div className="flex w-full flex-wrap items-center gap-1 md:w-auto md:shrink-0 md:justify-end">
            {canPlayVideo && (
                <MediaActionIconButton
                    label={`${dict.result.playVideo}: ${title}`}
                    text={dict.result.playVideo}
                    icon={Play}
                    variant="ghost"
                    size="xs"
                    className="h-7"
                    onClick={() => onPlay('video')}
                />
            )}
            {canPlayAudio && (
                <MediaActionIconButton
                    label={`${dict.result.playAudio}: ${title}`}
                    text={dict.result.playAudio}
                    icon={Headphones}
                    variant="ghost"
                    size="xs"
                    className="h-7"
                    onClick={() => onPlay('audio')}
                />
            )}
            {canDownloadVideo && (
                <MediaActionIconButton
                    label={`${dict.result.downloadVideo}: ${title}`}
                    text={dict.result.downloadVideo}
                    icon={VideoDownloadIcon}
                    variant="outline"
                    size="xs"
                    className="h-7"
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
                    variant="outline"
                    size="xs"
                    className="h-7"
                    disabled={audioLoading}
                    loading={audioLoading}
                    onClick={() => onDownloadAudio(audioDownloadUrl!)}
                />
            )}
        </div>
    );
}
