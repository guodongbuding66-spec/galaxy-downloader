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
        <header className="flex min-w-0 items-start gap-3 border-b px-3 py-2.5 sm:px-3.5">
            <div className="flex min-w-0 flex-1 flex-col gap-0.5 sm:flex-row sm:items-baseline sm:gap-2.5">
                <h2 className="min-w-0 flex-1 line-clamp-2 text-sm font-semibold leading-5 tracking-[-0.01em]" title={title}>
                    {title}
                </h2>
                {duration != null ? (
                    <span className="shrink-0 text-[11px] font-medium tabular-nums leading-5 text-muted-foreground">
                        {formatDuration(duration)}
                    </span>
                ) : null}
            </div>

            <div className="flex shrink-0 items-center gap-1">
                {canSharePlayLink ? (
                    <Button
                        variant="ghost"
                        size="icon"
                        className="text-muted-foreground hover:text-foreground"
                        onClick={onCopyShareLink}
                        aria-label={dict.result.sharePlayLink}
                        title={dict.result.sharePlayLink}
                    >
                        <Share2 className="h-4 w-4" aria-hidden="true" />
                    </Button>
                ) : null}
                <Button
                    variant="ghost"
                    size="icon"
                    className="text-muted-foreground hover:text-foreground"
                    onClick={onClose}
                    aria-label={dict.result.previewPlayerClose}
                    title={dict.result.previewPlayerClose}
                >
                    <X className="h-4 w-4" aria-hidden="true" />
                </Button>
            </div>
        </header>
    );
}
