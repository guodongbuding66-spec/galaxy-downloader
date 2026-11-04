'use client';

import { startTransition, useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import dynamic from 'next/dynamic';
import { usePathname, useSearchParams } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';

import { toast } from '@/lib/deferred-toast';
import { DeferredAudioExtractDialog } from '@/components/deferred-audio-extract-dialog';
import { useTopBarActions } from '@/components/layout/top-bar-actions';
import type { AudioExtractTask } from '@/components/audio-tool/types';
import type { MediaPreviewRequest } from '@/components/downloader/media-preview';
import { buildResultPreviewForSelection } from '@/components/downloader/media-preview';
import { LocalEngineSetupHint } from '@/components/downloader/LocalEngineSetupHint';
import { BatchWorkbench } from '@/components/downloader/BatchWorkbench';
import { workbenchUiCopy } from '@/components/downloader/workbench-copy';
import {
    ArrowUp,
    ChevronDown,
    ClipboardPaste,
    Loader2,
    PackageCheck,
    Link2,
    Layers3,
    Music2,
    History,
    ImageIcon,
    MonitorDown,
    Sparkles,
    X,
} from 'lucide-react';

import type { DownloadRecord } from './download-history';
import { useLocalStorageState } from '@/hooks/use-local-storage-state';
import { useInstallPrompt } from '@/hooks/use-install-prompt';
import type { UnifiedParseResult } from '@/lib/types';
import { Platform } from '@/lib/types';
import { DOWNLOAD_HISTORY_MAX_COUNT, DOWNLOAD_HISTORY_STORAGE_KEY } from '@/lib/constants';
import { useDictionary } from '@/i18n/client';
import { isApiRequestError, resolveApiErrorMessage } from '@/lib/api-errors';
import { getPlatformLabel, normalizePlatform } from '@/lib/platforms';
import { UnifiedParseReloadError, requestUnifiedParse } from '@/lib/unified-parse';

const UnifiedDownloaderLowerSections = dynamic(
    () => import('./unified-downloader-lower-sections').then((m) => m.UnifiedDownloaderLowerSections),
    { ssr: false }
);

interface UnifiedDownloaderProps {
    leftRail?: ReactNode;
    rightRail?: ReactNode;
    mobileAd?: ReactNode;
    mobileGuides?: ReactNode;
    heroMeta?: ReactNode;
    footer?: ReactNode;
}

interface ActivePreview extends MediaPreviewRequest {
    origin: 'share' | 'result' | 'user';
}

type WorkbenchCopy = {
    inputLabel: string;
    clearInput: string;
    pageDescription: string;
    helperTitle: string;
    helperDescription: string;
};

const WORKBENCH_COPY: Record<string, WorkbenchCopy> = {
    zh: {
        inputLabel: '媒体链接或分享文本',
        clearInput: '清空链接',
        pageDescription: '首次使用请先下载并打开 Galaxy Local Engine，再粘贴链接解析；支持视频、音频、纯音乐、图文以及 M3U8/HLS 流媒体。',
        helperTitle: '工具与平台说明',
        helperDescription: '历史记录、平台说明和辅助工具按需展开。',
    },
    'zh-tw': {
        inputLabel: '媒體連結或分享文字',
        clearInput: '清空連結',
        pageDescription: '首次使用請先下載並開啟 Galaxy Local Engine，再貼上連結解析；支援影片、音訊、純音樂、圖文以及 M3U8/HLS 串流媒體。',
        helperTitle: '工具與平台說明',
        helperDescription: '歷史記錄、平台說明與輔助工具按需展開。',
    },
    en: {
        inputLabel: 'Media URL or shared text',
        clearInput: 'Clear link',
        pageDescription: 'First download and open Galaxy Local Engine, then paste a link to parse video, audio, music, image posts, and M3U8/HLS media.',
        helperTitle: 'Tools and platform notes',
        helperDescription: 'History, platform notes and secondary tools stay collapsed until needed.',
    },
    ja: {
        inputLabel: 'メディアURLまたは共有テキスト',
        clearInput: 'リンクを消去',
        pageDescription: '初回は Galaxy Local Engine をダウンロードして起動し、その後リンクを貼り付けて動画・音声・音楽・画像投稿・M3U8/HLS を解析します。',
        helperTitle: 'ツールとプラットフォーム情報',
        helperDescription: '履歴や補助ツールは必要なときだけ展開できます。',
    },
    es: {
        inputLabel: 'URL del medio o texto compartido',
        clearInput: 'Borrar enlace',
        pageDescription: 'Primero descarga y abre Galaxy Local Engine; después pega un enlace para analizar vídeo, audio, música, publicaciones con imágenes y M3U8/HLS.',
        helperTitle: 'Herramientas y notas de plataformas',
        helperDescription: 'El historial y las herramientas secundarias permanecen plegados hasta que los necesites.',
    },
    ru: {
        inputLabel: 'Ссылка на медиа или текст публикации',
        clearInput: 'Очистить ссылку',
        pageDescription: 'Сначала скачайте и откройте Galaxy Local Engine, затем вставьте ссылку для разбора видео, аудио, музыки, публикаций с изображениями и M3U8/HLS.',
        helperTitle: 'Инструменты и сведения о платформах',
        helperDescription: 'История и вспомогательные инструменты раскрываются только при необходимости.',
    },
};

function resolveWorkbenchCopy(pathname: string | null): WorkbenchCopy {
    const locale = pathname?.split('/').filter(Boolean)[0] || 'en';
    return WORKBENCH_COPY[locale] || WORKBENCH_COPY.en;
}

export function UnifiedDownloader({
    leftRail,
    rightRail,
    mobileAd,
    heroMeta,
    footer,
}: UnifiedDownloaderProps) {
    const dict = useDictionary();
    const { setActions: setTopBarActions } = useTopBarActions();
    const pathname = usePathname();
    const workbenchCopy = resolveWorkbenchCopy(pathname);
    const workspace = workbenchUiCopy(pathname);
    const [inputMode, setInputMode] = useState<'single' | 'batch'>('single');
    const searchParams = useSearchParams();
    const [url, setUrl] = useState('');
    const [loading, setLoading] = useState(false);
    const [isCoolingDown, setIsCoolingDown] = useState(false);
    const [error, setError] = useState('');
    const lastParseTimeRef = useRef<number>(0);
    const [audioToolMounted, setAudioToolMounted] = useState(false);
    const [audioToolOpen, setAudioToolOpen] = useState(false);
    const [audioToolEntry, setAudioToolEntry] = useState<'toolbar' | 'result'>('toolbar');
    const [audioToolTask, setAudioToolTask] = useState<AudioExtractTask | null>(null);
    const [parseResult, setParseResult] = useState<UnifiedParseResult['data'] | null>(null);
    const [activePreview, setActivePreview] = useState<ActivePreview | null>(null);
    const [showBackToTop, setShowBackToTop] = useState(false);
    const historyRef = useRef<HTMLDivElement>(null);
    const urlInputRef = useRef<HTMLTextAreaElement>(null);
    const handledShareTaskRef = useRef<string | null>(null);

    const [downloadHistory, setDownloadHistory, historyHydrated] = useLocalStorageState<DownloadRecord[]>(DOWNLOAD_HISTORY_STORAGE_KEY, {
        defaultValue: []
    });
    const { canPrompt, promptInstall, dismiss } = useInstallPrompt();
    const hasPromptedInstall = useRef(false);
    const addToHistory = useCallback((record: DownloadRecord) => {
        const normalizedUrl = record.url.trim();
        setDownloadHistory(prev => [
            record,
            ...(prev || []).filter((item) => item.url.trim() !== normalizedUrl)
        ].slice(0, DOWNLOAD_HISTORY_MAX_COUNT));
    }, [setDownloadHistory]);

    const clearDownloadHistory = () => {
        setDownloadHistory([]);
    };

    const openToolbarAudioTool = useCallback(() => {
        setAudioToolMounted(true);
        setAudioToolEntry('toolbar');
        setAudioToolTask(null);
        setAudioToolOpen(true);
    }, []);

    const openResultAudioExtract = (task: AudioExtractTask) => {
        setAudioToolMounted(true);
        setAudioToolEntry('result');
        setAudioToolTask(task);
        setAudioToolOpen(true);
    };

    const handleUnifiedParse = useCallback(async (videoUrl: string) => {
        void import('./unified-downloader-lower-sections');

        const apiResult = await requestUnifiedParse(videoUrl);
        const normalizedData = {
            ...apiResult.data,
            platform: normalizePlatform(apiResult.data.platform),
        };
        const platformCode = normalizedData.platform;
        const platformLabel = getPlatformLabel(platformCode, dict);
        const displayTitle = normalizedData.title || normalizedData.desc || dict.history.unknownTitle;
        const nextRecord: DownloadRecord = {
            url: normalizedData.url || videoUrl,
            title: displayTitle,
            timestamp: Date.now(),
            platform: platformCode as Platform
        };

        startTransition(() => {
            setParseResult(normalizedData);
            addToHistory(nextRecord);
        });

        toast.success(dict.toast.douyinParseSuccess, {
            description: `${platformLabel}: ${displayTitle}`,
        });

        if (canPrompt && !hasPromptedInstall.current) {
            hasPromptedInstall.current = true;
            toast(dict.toast.installTitle, {
                description: dict.toast.installDescription,
                duration: 10000,
                action: {
                    label: dict.toast.installAction,
                    onClick: promptInstall,
                },
                onDismiss: dismiss,
            });
        }
        return normalizedData;
    }, [addToHistory, canPrompt, dict, dismiss, promptInstall]);

    const closeParseResult = () => {
        setParseResult(null);
        setActivePreview(null);
    };

    const openResultPreview = useCallback((request: MediaPreviewRequest) => {
        setActivePreview({
            ...request,
            autoplay: request.autoplay ?? false,
            origin: request.origin ?? 'result',
        });
    }, [setActivePreview]);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (loading || isCoolingDown) return;

        if (!url.trim()) {
            setError(dict.errors.emptyUrl);
            return;
        }

        const now = Date.now();
        if (now - lastParseTimeRef.current < 3000) {
            return;
        }
        lastParseTimeRef.current = now;
        setIsCoolingDown(true);
        setTimeout(() => setIsCoolingDown(false), 3000);

        setLoading(true);
        setError('');
        setParseResult(null);
        setActivePreview(null);

        try {
            await handleUnifiedParse(url.trim());
        } catch (err) {
            if (err instanceof UnifiedParseReloadError) {
                setLoading(false);
                return;
            }

            if (isApiRequestError(err)) {
                console.error('Unified parse request failed', {
                    code: err.code,
                    status: err.status,
                    requestId: err.requestId,
                    details: err.details,
                });
            }

            const errorMessage = resolveApiErrorMessage(err, dict);
            setError(errorMessage);
            toast.error(dict.errors.downloadFailed, {
                description: errorMessage
            });
        }

        setLoading(false);
    };

    const handleRedownload = (url: string) => {
        setInputMode('single');
        setUrl(url);
        setParseResult(null);
        setActivePreview(null);
        toast(dict.toast.linkFilledForRedownload, {
            description: dict.toast.clickToRedownloadDesc,
        });
        window.scrollTo({ top: 0, behavior: 'smooth' });
    };

    const sharedPlaySourceUrl = searchParams.get('play')?.trim() ?? '';
    const sharedAutoplayRequested = searchParams.get('autoplay') === '1';
    const sharedPlayItem = searchParams.get('item')?.trim() || undefined;
    const sharedPlayType = searchParams.get('type') === 'audio'
        ? 'audio'
        : searchParams.get('type') === 'video'
            ? 'video'
            : undefined;
    const hasDownloadHistory = downloadHistory.length > 0;
    const showHistoryShortcut = historyHydrated && hasDownloadHistory;
    const scrollToHistory = useCallback(() => {
        if (historyRef.current) {
            const top = historyRef.current.getBoundingClientRect().top + window.scrollY - 64;
            window.scrollTo({ top, behavior: 'smooth' });
        }
    }, []);

    useEffect(() => {
        setTopBarActions({
            showHistoryShortcut,
            onHistoryClick: scrollToHistory,
            showAudioTool: true,
            onAudioToolClick: openToolbarAudioTool,
        });

        return () => {
            setTopBarActions({});
        };
    }, [
        openToolbarAudioTool,
        scrollToHistory,
        setTopBarActions,
        showHistoryShortcut,
    ]);

    useEffect(() => {
        if (!sharedPlaySourceUrl) {
            return;
        }

        const taskKey = [
            sharedPlaySourceUrl,
            sharedPlayItem ?? '',
            sharedPlayType ?? '',
            sharedAutoplayRequested ? '1' : '0',
        ].join('::');
        if (handledShareTaskRef.current === taskKey) {
            return;
        }
        handledShareTaskRef.current = taskKey;

        let cancelled = false;

        const runSharedPlayback = async () => {
            setLoading(true);
            setError('');
            setParseResult(null);
            setUrl(sharedPlaySourceUrl);
            setActivePreview(null);

            try {
                const parsed = await handleUnifiedParse(sharedPlaySourceUrl);
                if (cancelled) {
                    return;
                }

                const sharePreview = buildResultPreviewForSelection(parsed, {
                    item: sharedPlayItem,
                    mediaType: sharedPlayType,
                    autoplay: sharedAutoplayRequested,
                });

                setActivePreview(sharePreview ? {
                    ...sharePreview,
                    origin: 'share',
                } : null);
            } catch (err) {
                if (cancelled) {
                    return;
                }

                if (err instanceof UnifiedParseReloadError) {
                    return;
                }

                if (isApiRequestError(err)) {
                    console.error('Shared playback parse failed', {
                        code: err.code,
                        status: err.status,
                        requestId: err.requestId,
                        details: err.details,
                    });
                }

                const errorMessage = resolveApiErrorMessage(err, dict);
                setError(errorMessage);
                toast.error(dict.errors.downloadFailed, {
                    description: errorMessage,
                });
            } finally {
                if (!cancelled) {
                    setLoading(false);
                }
            }
        };

        void runSharedPlayback();

        return () => {
            cancelled = true;
        };
    }, [
        dict,
        handleUnifiedParse,
        sharedAutoplayRequested,
        sharedPlayItem,
        sharedPlaySourceUrl,
        sharedPlayType,
    ]);

    useEffect(() => {
        let idleId: number | null = null;
        let timerId: ReturnType<typeof setTimeout> | null = null;

        const preloadInteractiveChunks = () => {
            void import('./unified-downloader-lower-sections');
        };

        if (typeof window !== 'undefined' && 'requestIdleCallback' in window) {
            idleId = window.requestIdleCallback(() => {
                preloadInteractiveChunks();
            }, { timeout: 3000 });
        } else {
            timerId = setTimeout(() => {
                preloadInteractiveChunks();
            }, 1200);
        }

        return () => {
            if (idleId !== null && 'cancelIdleCallback' in window) {
                window.cancelIdleCallback(idleId);
            }
            if (timerId !== null) {
                clearTimeout(timerId);
            }
        };
    }, []);

    useEffect(() => {
        let ticking = false;

        const updateVisibility = () => {
            const shouldShow = window.scrollY > 800;
            setShowBackToTop((prev) => (prev === shouldShow ? prev : shouldShow));
            ticking = false;
        };

        const handleScroll = () => {
            if (ticking) {
                return;
            }
            ticking = true;
            window.requestAnimationFrame(updateVisibility);
        };

        handleScroll();
        window.addEventListener('scroll', handleScroll, { passive: true });

        return () => {
            window.removeEventListener('scroll', handleScroll);
        };
    }, []);

    return (
        <div className="min-h-screen flex flex-col bg-background">
            <DeferredAudioExtractDialog
                mounted={audioToolMounted}
                open={audioToolOpen}
                onOpenChange={(nextOpen) => {
                    setAudioToolOpen(nextOpen);
                    if (!nextOpen) {
                        setAudioToolTask(null);
                        setAudioToolEntry('toolbar');
                    }
                }}
                entry={audioToolEntry}
                autoExtractTask={audioToolTask}
            />

            <main id="main-content" className="flex-1 px-4 py-5 sm:px-6 lg:px-8 lg:py-8">
                <div className="mx-auto grid w-full max-w-[1440px] gap-6 lg:grid-cols-[192px_minmax(0,1fr)] lg:gap-8">
                    <aside className="min-w-0">
                        <nav className="workspace-nav lg:sticky lg:top-24" aria-label={workspace.workspace}>
                            <p className="mb-4 hidden px-3 text-xs font-medium text-muted-foreground lg:block">{workspace.workspace}</p>
                            <button type="button" aria-pressed={inputMode === 'single'} onClick={() => {
                                setInputMode('single');
                                requestAnimationFrame(() => urlInputRef.current?.focus());
                            }}><Link2 aria-hidden="true" />{workspace.single}</button>
                            <button type="button" aria-pressed={inputMode === 'batch'} onClick={() => setInputMode('batch')}><Layers3 aria-hidden="true" />{workspace.batch}</button>
                            <button type="button" onClick={openToolbarAudioTool}><Music2 aria-hidden="true" />{workspace.audio}</button>
                            <button type="button" onClick={scrollToHistory} disabled={!showHistoryShortcut}><History aria-hidden="true" />{workspace.history}</button>
                        </nav>
                    </aside>
                    <div className="min-w-0 space-y-6">
                        <header className="space-y-2">
                            <h1 className="text-balance text-2xl font-semibold tracking-[-0.035em] sm:text-[32px] sm:leading-tight">{workspace.title}</h1>
                            <p className="max-w-2xl text-sm leading-6 text-muted-foreground">{workspace.description}</p>
                        </header>

                        <section className="workspace-input-panel rounded-2xl border bg-card p-4 sm:p-5" aria-label={workspace.workspace}>
                            <div className="mb-4 flex flex-col gap-3 border-b pb-4 sm:flex-row sm:items-start sm:justify-between">
                                <div className="flex shrink-0 items-center gap-2 text-sm font-semibold">
                                    {inputMode === 'single' ? <Link2 className="h-4 w-4 text-primary" aria-hidden="true" /> : <Layers3 className="h-4 w-4 text-primary" aria-hidden="true" />}
                                    {inputMode === 'single' ? workspace.single : workspace.batch}
                                </div>
                                <LocalEngineSetupHint className="sm:max-w-[580px] sm:justify-end" />
                            </div>
                            <div hidden={inputMode !== 'single'}>
                                <form onSubmit={handleSubmit} aria-busy={loading}>
                                    <label htmlFor="url" className="mb-2 block text-xs font-medium text-muted-foreground">{workbenchCopy.inputLabel}</label>
                                    <div className="relative rounded-xl border border-input bg-background focus-within:border-primary focus-within:ring-2 focus-within:ring-ring/15">
                                        <Textarea
                                            id="url" ref={urlInputRef} value={url}
                                            onChange={(e) => setUrl(e.target.value)}
                                            onKeyDown={(e) => {
                                                if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                                                    e.preventDefault();
                                                    e.currentTarget.form?.requestSubmit();
                                                }
                                            }}
                                            placeholder={dict.unified.placeholder} required
                                            aria-describedby="link-input-help" aria-invalid={Boolean(error)}
                                            className="min-h-[112px] resize-y border-0 bg-transparent py-3 pe-12 ps-3 text-sm leading-6 shadow-none focus-visible:ring-0"
                                        />
                                        <Button type="button" variant="ghost" size="icon" className="absolute end-2 top-2 h-9 w-9 text-muted-foreground" aria-label={dict.form.pasteButton} title={dict.form.pasteButton}
                                            onClick={async () => {
                                                try {
                                                    setUrl(await navigator.clipboard.readText());
                                                    urlInputRef.current?.focus();
                                                    toast.success(dict.toast.linkFilled);
                                                } catch (err) {
                                                    console.error('Failed to read clipboard:', err);
                                                    toast.error(dict.errors.clipboardFailed, { description: dict.errors.clipboardPermission });
                                                }
                                            }}><ClipboardPaste className="h-4 w-4" aria-hidden="true" /></Button>
                                    </div>
                                    <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                                        <p id="link-input-help" className="text-xs text-muted-foreground">{workspace.shortcut}</p>
                                        <div className="ms-auto flex items-center gap-2">
                                            <Button type="button" variant="ghost" disabled={!url.length} onClick={() => { setUrl(''); setError(''); urlInputRef.current?.focus(); }}>
                                                <X className="h-4 w-4" aria-hidden="true" />{workbenchCopy.clearInput}
                                            </Button>
                                            <Button type="submit" className="min-w-[140px] rounded-lg" disabled={loading || isCoolingDown || !url.trim()}>
                                                {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <PackageCheck className="h-4 w-4" aria-hidden="true" />}
                                                {loading ? workspace.parsing : workspace.parse}
                                            </Button>
                                        </div>
                                    </div>
                                    {error && <p role="alert" className="mt-3 rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>}
                                    <div className="mt-4 flex flex-wrap items-start justify-between gap-2 border-t pt-3 text-[11px] leading-5 text-muted-foreground">
                                        <p className="max-w-2xl">{dict.page.copyrightBilibiliRestriction}</p>
                                        {heroMeta ? <div>{heroMeta}</div> : null}
                                    </div>
                                </form>
                            </div>
                            <div hidden={inputMode !== 'batch'}><BatchWorkbench defaultOpen active={inputMode === 'batch'} /></div>
                        </section>

                        {!parseResult && !loading && inputMode === 'single' && (
                            <section className="workspace-empty rounded-2xl border border-dashed px-5 py-8 sm:px-8 sm:py-10">
                                <div className="mx-auto max-w-2xl">
                                    <div className="mb-5 flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 text-primary"><MonitorDown className="h-6 w-6" aria-hidden="true" /></div>
                                    <h2 className="text-lg font-semibold tracking-tight">{workspace.emptyTitle}</h2>
                                    <p className="mt-2 max-w-xl text-sm leading-6 text-muted-foreground">{workspace.emptyDescription}</p>
                                    <div className="mt-7 grid gap-5 sm:grid-cols-3">
                                        {[{ icon: Sparkles, title: workspace.quality, description: workspace.qualityDescription }, { icon: ImageIcon, title: workspace.originals, description: workspace.originalsDescription }, { icon: MonitorDown, title: workspace.local, description: workspace.localDescription }].map(({ icon: Icon, title, description }) => (
                                            <div key={title} className="min-w-0"><Icon className="mb-2 h-4 w-4 text-muted-foreground" aria-hidden="true" /><h3 className="text-xs font-medium">{title}</h3><p className="mt-1 text-xs leading-5 text-muted-foreground">{description}</p></div>
                                        ))}
                                    </div>
                                </div>
                            </section>
                        )}
                        {loading && <div role="status" aria-live="polite" className="flex min-h-36 items-center justify-center gap-3 rounded-2xl border bg-card text-sm text-muted-foreground"><Loader2 className="h-5 w-5 animate-spin text-primary" aria-hidden="true" />{workspace.parsing}</div>}

                        <UnifiedDownloaderLowerSections
                            parseResult={parseResult} onCloseParseResult={closeParseResult} onOpenExtractAudio={openResultAudioExtract}
                            onRequestPreview={openResultPreview} onClearPreview={() => setActivePreview(null)} activePreview={activePreview}
                            mobileAd={mobileAd} downloadHistory={downloadHistory} clearHistory={clearDownloadHistory}
                            onRedownload={handleRedownload} historyRef={historyRef} historyHydrated={historyHydrated}
                        />
                        {(leftRail || rightRail) && (
                            <details className="group border-t pt-1">
                                <summary className="flex cursor-pointer list-none items-center justify-between gap-3 rounded-md px-1 py-2 text-sm focus-visible:ring-2 focus-visible:ring-ring">
                                    <div className="min-w-0"><span className="font-medium">{workbenchCopy.helperTitle}</span><span className="ms-2 hidden text-xs font-normal text-muted-foreground md:inline">{workbenchCopy.helperDescription}</span></div>
                                    <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-150 group-open:rotate-180" aria-hidden="true" />
                                </summary>
                                <div className="grid gap-3 pb-2 pt-2 md:grid-cols-2 xl:grid-cols-3 [&>*]:min-w-0">{leftRail}{rightRail}</div>
                            </details>
                        )}
                    </div>
                </div>
            </main>

            {footer}

            <Button
                type="button"
                variant="outline"
                size="icon"
                className={`fixed right-4 bottom-[calc(1rem+env(safe-area-inset-bottom))] z-30 h-8 w-8 rounded-md bg-card transition-[opacity,transform] duration-150 ${
                    showBackToTop
                        ? 'pointer-events-auto opacity-100 translate-y-0'
                        : 'pointer-events-none opacity-0 translate-y-2'
                }`}
                aria-label={dict.common.backToTop}
                onClick={() => {
                    window.scrollTo({ top: 0, behavior: 'smooth' });
                }}
            >
                <ArrowUp className="h-3.5 w-3.5" aria-hidden="true" />
            </Button>
        </div>
    );
}
