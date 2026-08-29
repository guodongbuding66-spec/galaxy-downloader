import type { AudioExtractTask } from '@/components/audio-tool/types';
import { Card, CardContent } from '@/components/ui/card';
import type { UnifiedParseResult } from '@/lib/types';

import { ImageNoteGrid } from './ImageNoteGrid';
import { type MediaPreviewRequest } from './media-preview';
import { ResultCardHeader } from './ResultCardHeader';
import { getResultMediaActions, resolveResultDisplayImages } from './result-card-visibility';
import { SinglePartButtons } from './SinglePartButtons';

type ResultData = NonNullable<UnifiedParseResult['data']>;

interface ImageResultPanelProps {
    result: ResultData;
    onClose: () => void;
    onOpenExtractAudio: (task: AudioExtractTask) => void;
    onRequestPreview: (request: MediaPreviewRequest) => void;
    activePreview?: MediaPreviewRequest | null;
}

export function ImageResultPanel({
    result,
    onClose,
    onOpenExtractAudio,
    onRequestPreview,
}: ImageResultPanelProps) {
    const displayImages = resolveResultDisplayImages({
        noteType: result.noteType,
        images: result.images,
        coverUrl: result.cover,
    });

    const { audioAction } = getResultMediaActions({
        videoAudioMode: result.videoAudioMode,
        mediaActions: result.mediaActions,
        videoDownloadUrl: result.downloadVideoUrl || result.originDownloadVideoUrl,
        audioDownloadUrl: result.downloadAudioUrl || result.originDownloadAudioUrl || null,
        originDownloadVideoUrl: result.originDownloadVideoUrl,
        originDownloadAudioUrl: result.originDownloadAudioUrl,
    });
    const showAudioActions = audioAction !== 'hide';

    return (
        <Card className="overflow-hidden">
            <ResultCardHeader
                title={result.title}
                duration={result.duration}
                canSharePlayLink={false}
                onCopyShareLink={() => {}}
                onClose={onClose}
            />
            <CardContent className="p-4 sm:p-5">
                <div className="space-y-4">
                    <ImageNoteGrid images={displayImages} title={result.title} />
                    {showAudioActions ? (
                        <div className="border-t pt-4">
                            <SinglePartButtons
                                result={result}
                                onOpenExtractAudio={onOpenExtractAudio}
                                onOpenHlsDownload={() => {}}
                                onRequestPreview={onRequestPreview}
                            />
                        </div>
                    ) : null}
                </div>
            </CardContent>
        </Card>
    );
}
