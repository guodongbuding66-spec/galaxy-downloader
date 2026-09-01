import type { AudioExtractTask } from '@/components/audio-tool/types';
import type { UnifiedParseResult } from '@/lib/types';

import { DocumentTextActions } from './DocumentTextActions';
import { EmbeddedVideoList } from './EmbeddedVideoList';
import { ImageArchiveActions } from './ImageArchiveActions';
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
    const documentText = result.textContent || result.desc || '';
    const embeddedVideos = result.videos || [];

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
        <section className="overflow-hidden rounded-lg border bg-card">
            <ResultCardHeader
                title={result.title}
                duration={result.duration}
                canSharePlayLink={false}
                onCopyShareLink={() => {}}
                onClose={onClose}
            />
            <div className="space-y-2.5 p-2 sm:p-2.5">
                <DocumentTextActions
                    title={result.title}
                    text={documentText}
                    markdown={result.markdownContent}
                    author={result.author}
                    publishedAt={result.publishedAt}
                    sourceUrl={result.url}
                />

                {displayImages.length > 1 ? (
                    <ImageArchiveActions
                        images={displayImages}
                        title={result.title}
                        description={documentText}
                        markdownContent={result.markdownContent}
                        author={result.author}
                        publishedAt={result.publishedAt}
                        sourceUrl={result.url}
                        platform={result.platform}
                    />
                ) : null}

                <div className={showAudioActions
                    ? 'grid gap-2.5 lg:grid-cols-[minmax(0,1fr)_minmax(300px,380px)] lg:items-start'
                    : 'min-w-0'}
                >
                    <div className="min-w-0 space-y-2.5">
                        {displayImages.length > 0 ? (
                            <ImageNoteGrid
                                images={displayImages}
                                title={result.title}
                                description={documentText}
                                markdownContent={result.markdownContent}
                                author={result.author}
                                publishedAt={result.publishedAt}
                                sourceUrl={result.url}
                            />
                        ) : null}
                        {embeddedVideos.length > 0 ? (
                            <EmbeddedVideoList videos={embeddedVideos} />
                        ) : null}
                    </div>
                    {showAudioActions ? (
                        <aside className="min-w-0 border-t pt-2.5 lg:sticky lg:top-2.5 lg:border-s lg:border-t-0 lg:ps-2.5 lg:pt-0">
                            <SinglePartButtons
                                result={result}
                                onOpenExtractAudio={onOpenExtractAudio}
                                onOpenHlsDownload={() => {}}
                                onRequestPreview={onRequestPreview}
                            />
                        </aside>
                    ) : null}
                </div>
            </div>
        </section>
    );
}
