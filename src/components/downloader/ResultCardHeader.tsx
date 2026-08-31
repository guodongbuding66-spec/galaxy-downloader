import { Share2, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { useDictionary } from '@/i18n/client';
import { formatDuration } from '@/lib/utils';

interface ResultCardHeaderProps {
    title: string;
    duration?: number | null;
    canSharePlayLink: boolean;
    onCopyShareLink: () => void;
    onClose: () => void;
}

export function ResultCardHeader({
    title,
    duration,
    canSharePlayLink,
    onCopyShareLink,
    onClose,
}: ResultCardHeaderProps) {
    const dict = useDictionary();

    return (
        <header className="flex min-w-0 items-start gap-3 border-b border-border/60 px-3 py-2.5 sm:px-4">
            <div className="min-w-0 flex-1">
                <div className="text-[11px] font-medium text-muted-foreground">{dict.result.title}</div>
                <div className="mt-0.5 flex min-w-0 items-baseline gap-2">
                    <h2 className="min-w-0 flex-1 truncate text-sm font-semibold tracking-tight" title={title}>{title}</h2>
                    {duration != null ? (
                        <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">{formatDuration(duration)}</span>
                    ) : null}
                </div>
            </div>

            <div className="flex shrink-0 items-center gap-1">
                {canSharePlayLink ? (
                    <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 transition-transform duration-150 active:scale-[0.94]"
                        onClick={onCopyShareLink}
                        aria-label={dict.result.sharePlayLink}
                        title={dict.result.sharePlayLink}
                    >
                        <Share2 className="h-3.5 w-3.5" aria-hidden="true" />
                    </Button>
                ) : null}
                <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 transition-transform duration-150 active:scale-[0.94]"
                    onClick={onClose}
                    aria-label={dict.result.previewPlayerClose}
                >
                    <X className="h-3.5 w-3.5" aria-hidden="true" />
                </Button>
            </div>
        </header>
    );
}
