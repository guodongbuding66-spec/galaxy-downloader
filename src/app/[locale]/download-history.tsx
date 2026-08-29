'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
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
import { ChevronsUpDown, ExternalLink, History, RotateCcw, Search, Trash2 } from 'lucide-react';
import { toast } from '@/lib/deferred-toast';
import { useDictionary } from '@/i18n/client';
import { PlatformBadge } from '@/components/platform-badge';
import { Platform } from '../../lib/types';

export interface DownloadRecord {
    url: string;
    title: string;
    timestamp: number;
    platform: Platform;
}

interface DownloadHistoryProps {
    downloadHistory: DownloadRecord[];
    clearHistory: () => void;
    onRedownload?: (url: string) => void;
    defaultOpen?: boolean;
}

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

export function DownloadHistory({
    downloadHistory,
    clearHistory,
    onRedownload,
    defaultOpen = true,
}: DownloadHistoryProps) {
    const dict = useDictionary();
    const [isOpen, setIsOpen] = useState(defaultOpen);
    const [searchQuery, setSearchQuery] = useState('');

    const handleConfirmClearHistory = () => {
        clearHistory();
        toast.success(dict.history.cleared);
    };

    if (!downloadHistory || downloadHistory.length === 0) {
        return null;
    }

    const normalizedQuery = searchQuery.trim().toLowerCase();
    const filteredHistory = normalizedQuery
        ? downloadHistory.filter((record) => record.title.toLowerCase().includes(normalizedQuery))
        : downloadHistory;

    return (
        <Card className="overflow-hidden">
            <Collapsible open={isOpen} onOpenChange={setIsOpen}>
                <CardHeader className="border-b bg-muted/20 p-4 sm:p-5">
                    <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                        <CollapsibleTrigger asChild>
                            <Button
                                variant="ghost"
                                className="min-h-11 w-full justify-start gap-3 px-2 text-start lg:w-auto"
                            >
                                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-background ring-1 ring-border">
                                    <History className="h-4 w-4" aria-hidden="true" />
                                </span>
                                <span className="min-w-0 flex-1">
                                    <span className="block text-base font-semibold tracking-tight">
                                        {dict.history.title}
                                    </span>
                                    <span className="mt-0.5 block text-xs tabular-nums text-muted-foreground">
                                        {filteredHistory.length} / {downloadHistory.length}
                                    </span>
                                </span>
                                <ChevronsUpDown className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                            </Button>
                        </CollapsibleTrigger>

                        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                            <div className="relative min-w-0 flex-1 sm:w-64 sm:flex-none">
                                <Search className="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
                                <Input
                                    value={searchQuery}
                                    onChange={(e) => setSearchQuery(e.target.value)}
                                    placeholder={dict.history.searchPlaceholder}
                                    aria-label={dict.history.searchPlaceholder}
                                    className="min-h-11 w-full ps-9 text-base sm:text-sm"
                                />
                            </div>

                            <AlertDialog>
                                <AlertDialogTrigger asChild>
                                    <Button
                                        variant="outline"
                                        className="min-h-11 gap-2 border-destructive/25 text-destructive hover:bg-destructive/10 hover:text-destructive"
                                    >
                                        <Trash2 className="h-4 w-4" aria-hidden="true" />
                                        {dict.history.clear}
                                    </Button>
                                </AlertDialogTrigger>
                                <AlertDialogContent className="sm:max-w-md">
                                    <AlertDialogHeader>
                                        <AlertDialogTitle>{dict.history.clear}?</AlertDialogTitle>
                                        <AlertDialogDescription>{dict.history.title}</AlertDialogDescription>
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
                    </div>
                </CardHeader>

                <CollapsibleContent>
                    <CardContent className="p-3 sm:p-4">
                        <div className="max-h-[min(58vh,34rem)] overflow-y-auto overscroll-contain pe-1">
                            {filteredHistory.length === 0 ? (
                                <p className="rounded-xl border border-dashed px-4 py-10 text-center text-sm text-muted-foreground">
                                    {dict.history.noSearchResults}
                                </p>
                            ) : (
                                <div className="space-y-2">
                                    {filteredHistory.map((record: DownloadRecord) => (
                                        <article
                                            key={`${record.url}-${record.timestamp}`}
                                            className="group flex min-w-0 flex-col gap-3 rounded-xl border bg-background p-3 transition-colors duration-150 hover:bg-muted/25 md:flex-row md:items-center md:justify-between"
                                        >
                                            <div className="min-w-0 flex-1 space-y-1.5">
                                                <h3 className="line-clamp-2 text-sm font-medium leading-5" title={record.title}>
                                                    {record.title}
                                                </h3>
                                                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                                                    <PlatformBadge platform={record.platform} />
                                                    <time dateTime={new Date(record.timestamp).toISOString()} className="tabular-nums">
                                                        {formatRecordTimestamp(record.timestamp)}
                                                    </time>
                                                </div>
                                            </div>

                                            <div className="grid grid-cols-2 gap-2 md:flex md:shrink-0">
                                                <Button variant="outline" size="sm" className="min-h-10 gap-1.5" asChild>
                                                    <a href={record.url} target="_blank" rel="noopener noreferrer">
                                                        <ExternalLink className="h-4 w-4" aria-hidden="true" />
                                                        {dict.history.viewSource}
                                                    </a>
                                                </Button>
                                                <Button
                                                    variant="secondary"
                                                    size="sm"
                                                    className="min-h-10 gap-1.5"
                                                    onClick={() => onRedownload?.(record.url)}
                                                >
                                                    <RotateCcw className="h-4 w-4" aria-hidden="true" />
                                                    {dict.history.redownload}
                                                </Button>
                                            </div>
                                        </article>
                                    ))}
                                </div>
                            )}
                        </div>
                    </CardContent>
                </CollapsibleContent>
            </Collapsible>
        </Card>
    );
}
