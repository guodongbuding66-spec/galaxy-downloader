'use client';

import type { ReactNode, RefObject } from 'react';
import dynamic from 'next/dynamic';
import type { AudioExtractTask } from '@/components/audio-tool/types';
import type { MediaPreviewRequest } from '@/components/downloader/media-preview';
import type { UnifiedParseResult } from '@/lib/types';
import { ResultCard } from '@/components/downloader/ResultCard';
import type { DownloadRecord } from './download-history';

const DownloadHistory = dynamic(
    () => import('./download-history').then((m) => m.DownloadHistory),
    { ssr: false }
);

interface UnifiedDownloaderLowerSectionsProps {
    parseResult: UnifiedParseResult['data'] | null;
    onCloseParseResult: () => void;
    onOpenExtractAudio: (task: AudioExtractTask) => void;
    onRequestPreview: (request: MediaPreviewRequest) => void;
    onClearPreview: () => void;
    activePreview?: MediaPreviewRequest | null;
    mobileAd?: ReactNode;
    mobileGuides?: ReactNode;
    downloadHistory: DownloadRecord[];
    clearHistory: () => void;
    onRedownload: (url: string) => void;
    historyRef: RefObject<HTMLDivElement | null>;
    historyHydrated: boolean;
}

export function UnifiedDownloaderLowerSections({
    parseResult,
    onCloseParseResult,
    onOpenExtractAudio,
    onRequestPreview,
    onClearPreview,
    activePreview,
    mobileAd,
    mobileGuides,
    downloadHistory,
    clearHistory,
    onRedownload,
    historyRef,
    historyHydrated,
}: UnifiedDownloaderLowerSectionsProps) {
    const hasDownloadHistory = downloadHistory.length > 0;

    return (
        <div className="space-y-6">
            {parseResult && (
                <section aria-live="polite">
                    <ResultCard
                        result={parseResult}
                        onClose={onCloseParseResult}
                        onOpenExtractAudio={onOpenExtractAudio}
                        onRequestPreview={onRequestPreview}
                        onClearPreview={onClearPreview}
                        activePreview={activePreview}
                    />
                </section>
            )}

            {mobileAd && (
                <div className="lg:hidden min-h-[250px] overflow-hidden rounded-2xl">
                    {mobileAd}
                </div>
            )}

            <section ref={historyRef} className="scroll-mt-20">
                {hasDownloadHistory ? (
                    <DownloadHistory
                        downloadHistory={downloadHistory}
                        clearHistory={clearHistory}
                        onRedownload={onRedownload}
                    />
                ) : !historyHydrated ? (
                    <div className="min-h-[84px]" aria-hidden />
                ) : null}
            </section>

            {mobileGuides && <div className="flex flex-col gap-4 lg:hidden">{mobileGuides}</div>}
        </div>
    );
}
