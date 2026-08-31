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
        <header className="flex min-w-0 items-center gap-3 border-b px-3 py-2 sm:px-3.5">
            <div className="flex min-w-0 flex-1 items-baseline gap-2">
                <h2 className="min-w-0 flex-1 truncate text-sm font-medium tracking-tight" title={title}>{title}</h2>
                {duration != null ? (
                    <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">{formatDuration(duration)}</span>
                ) : null}
            </div>

            <div className="flex shrink-0 items-center gap-0.5">
                {canSharePlayLink ? (
                    <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 rounded-md text-muted-foreground hover:text-foreground"
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
                    className="h-7 w-7 rounded-md text-muted-foreground hover:text-foreground"
                    onClick={onClose}
                    aria-label={dict.result.previewPlayerClose}
                    title={dict.result.previewPlayerClose}
                >
                    <X className="h-3.5 w-3.5" aria-hidden="true" />
                </Button>
            </div>
        </header>
    );
}
