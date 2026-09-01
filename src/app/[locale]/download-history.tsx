'use client';

import { useState } from 'react';
import { usePathname } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { Input } from '@/components/ui/input';
import { ChevronDown, ExternalLink, History, RotateCcw, Search, Trash2 } from 'lucide-react';
import { toast } from '@/lib/deferred-toast';
import { useDictionary } from '@/i18n/client';
import { PlatformBadge } from '@/components/platform-badge';
import { Platform } from '../../lib/types';

export interface RecentParseRecord {
    url: string;
    title: string;
    timestamp: number;
    platform: Platform;
}

/** @deprecated Parse success, not download completion. Use RecentParseRecord. */
export type DownloadRecord = RecentParseRecord;

interface DownloadHistoryProps {
    downloadHistory: RecentParseRecord[];
    clearHistory: () => void;
    onRedownload?: (url: string) => void;
    defaultOpen?: boolean;
}

type RecentParseCopy = {
    title: string;
    cleared: string;
    searchPlaceholder: string;
    noSearchResults: string;
    clearDescription: string;
};

const RECENT_PARSE_COPY: Record<string, RecentParseCopy> = {
    zh: {
        title: '最近解析',
        cleared: '最近解析记录已清空',
        searchPlaceholder: '搜索最近解析...',
        noSearchResults: '没有匹配的最近解析记录',
        clearDescription: '这只会清除浏览器中的最近解析链接，不会删除已下载文件或 Local Engine 的去重记录。',
    },
    'zh-tw': {
        title: '最近解析',
        cleared: '最近解析記錄已清除',
        searchPlaceholder: '搜尋最近解析...',
        noSearchResults: '沒有符合的最近解析記錄',
        clearDescription: '這只會清除瀏覽器中的最近解析連結，不會刪除已下載檔案或 Local Engine 的去重記錄。',
    },
    en: {
        title: 'Recent parses',
        cleared: 'Recent parse history cleared',
        searchPlaceholder: 'Search recent parses...',
        noSearchResults: 'No matching recent parses',
        clearDescription: 'This only clears parsed links stored in this browser. It does not delete downloaded files or the Local Engine download archive.',
    },
    ja: {
        title: '最近の解析',
        cleared: '最近の解析履歴を消去しました',
        searchPlaceholder: '最近の解析を検索...',
        noSearchResults: '一致する解析履歴はありません',
        clearDescription: 'このブラウザーに保存された解析済みリンクだけを消去します。ダウンロード済みファイルや Local Engine の重複防止記録は削除しません。',
    },
    es: {
        title: 'Análisis recientes',
        cleared: 'Se borraron los análisis recientes',
        searchPlaceholder: 'Buscar análisis recientes...',
        noSearchResults: 'No hay análisis recientes que coincidan',
        clearDescription: 'Solo borra los enlaces analizados guardados en este navegador. No elimina archivos descargados ni el archivo de deduplicación del motor local.',
    },
    ru: {
        title: 'Недавние разборы',
        cleared: 'История недавних разборов очищена',
        searchPlaceholder: 'Поиск недавних разборов...',
        noSearchResults: 'Совпадающих недавних разборов нет',
        clearDescription: 'Удаляются только разобранные ссылки из этого браузера. Скачанные файлы и архив дедупликации Local Engine не удаляются.',
    },
};

const DATE_TIME_FORMATTER = new Intl.DateTimeFormat(undefined, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
});

function formatRecordTimestamp(timestamp: number): string {
    return DATE_TIME_FORMATTER.format(new Date(timestamp)).replace(',', '');
}

function recentParseCopy(pathname: string | null): RecentParseCopy {
    const locale = pathname?.split('/').filter(Boolean)[0] || 'en';
    return RECENT_PARSE_COPY[locale] || RECENT_PARSE_COPY.en;
}

export function DownloadHistory({
    downloadHistory,
    clearHistory,
    onRedownload,
    defaultOpen = false,
}: DownloadHistoryProps) {
    const dict = useDictionary();
    const pathname = usePathname();
    const copy = recentParseCopy(pathname);
    const [isOpen, setIsOpen] = useState(defaultOpen);
    const [searchQuery, setSearchQuery] = useState('');

    const handleConfirmClearHistory = () => {
        clearHistory();
        toast.success(copy.cleared);
    };

    if (!downloadHistory || downloadHistory.length === 0) return null;

    const normalizedQuery = searchQuery.trim().toLowerCase();
    const filteredHistory = normalizedQuery
        ? downloadHistory.filter((record) => record.title.toLowerCase().includes(normalizedQuery))
        : downloadHistory;

    return (
        <section className="border-t">
            <Collapsible open={isOpen} onOpenChange={setIsOpen}>
                <CollapsibleTrigger asChild>
                    <button
                        type="button"
                        className="flex min-h-10 w-full items-center gap-2 px-1 py-2 text-left outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                    >
                        <History className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
                        <span className="min-w-0 flex-1 text-sm font-medium">{copy.title}</span>
                        <span className="text-[11px] tabular-nums text-muted-foreground">{downloadHistory.length}</span>
                        <ChevronDown className={`h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform duration-150 ${isOpen ? 'rotate-180' : ''}`} aria-hidden="true" />
                    </button>
                </CollapsibleTrigger>

                <CollapsibleContent>
                    <div className="pb-2 pt-1">
                        <div className="mb-2 flex items-center gap-1.5">
                            <div className="relative min-w-0 flex-1 sm:max-w-64">
                                <Search className="pointer-events-none absolute start-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
                                <Input
                                    value={searchQuery}
                                    onChange={(e) => setSearchQuery(e.target.value)}
                                    placeholder={copy.searchPlaceholder}
                                    aria-label={copy.searchPlaceholder}
                                    className="h-8 ps-8 text-xs"
                                />
                            </div>

                            <AlertDialog>
                                <AlertDialogTrigger asChild>
                                    <Button
                                        variant="ghost"
                                        size="xs"
                                        className="shrink-0 text-muted-foreground hover:text-destructive"
                                    >
                                        <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                                        {dict.history.clear}
                                    </Button>
                                </AlertDialogTrigger>
                                <AlertDialogContent className="sm:max-w-md">
                                    <AlertDialogHeader>
                                        <AlertDialogTitle>{dict.history.clear} {copy.title}?</AlertDialogTitle>
                                        <AlertDialogDescription>{copy.clearDescription}</AlertDialogDescription>
                                    </AlertDialogHeader>
                                    <AlertDialogFooter>
                                        <AlertDialogCancel>{dict.errors.cancel}</AlertDialogCancel>
                                        <AlertDialogAction
                                            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                                            onClick={handleConfirmClearHistory}
                                        >
                                            {dict.history.clear}
                                        </AlertDialogAction>
                                    </AlertDialogFooter>
                                </AlertDialogContent>
                            </AlertDialog>
                        </div>

                        <div className="max-h-[min(52vh,30rem)] overflow-y-auto overscroll-contain border-y">
                            {filteredHistory.length === 0 ? (
                                <p className="px-3 py-8 text-center text-xs text-muted-foreground">
                                    {copy.noSearchResults}
                                </p>
                            ) : (
                                <div className="divide-y">
                                    {filteredHistory.map((record: RecentParseRecord) => (
                                        <article
                                            key={`${record.url}-${record.timestamp}`}
                                            className="grid min-h-11 min-w-0 gap-1.5 px-1.5 py-1.5 transition-colors hover:bg-muted/50 md:grid-cols-[minmax(0,1fr)_auto] md:items-center"
                                        >
                                            <div className="flex min-w-0 items-center gap-2">
                                                <PlatformBadge platform={record.platform} />
                                                <h3 className="min-w-0 flex-1 truncate text-xs font-medium" title={record.title}>
                                                    {record.title}
                                                </h3>
                                                <time dateTime={new Date(record.timestamp).toISOString()} className="hidden shrink-0 text-[10px] tabular-nums text-muted-foreground sm:inline">
                                                    {formatRecordTimestamp(record.timestamp)}
                                                </time>
                                            </div>

                                            <div className="flex items-center gap-1 md:justify-end">
                                                <Button variant="ghost" size="xs" className="text-muted-foreground" asChild>
                                                    <a href={record.url} target="_blank" rel="noopener noreferrer">
                                                        <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                                                        {dict.history.viewSource}
                                                    </a>
                                                </Button>
                                                <Button
                                                    variant="ghost"
                                                    size="xs"
                                                    className="text-muted-foreground"
                                                    onClick={() => onRedownload?.(record.url)}
                                                >
                                                    <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                                                    {dict.history.redownload}
                                                </Button>
                                            </div>
                                        </article>
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>
                </CollapsibleContent>
            </Collapsible>
        </section>
    );
}
