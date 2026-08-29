import { Share2, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { CardHeader, CardTitle } from '@/components/ui/card';
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
        <CardHeader className="border-b bg-muted/20 p-4 sm:p-5">
            <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 space-y-1.5">
                    <CardTitle className="text-base font-semibold tracking-tight sm:text-lg">
                        {dict.result.title}
                    </CardTitle>
                    <p
                        className="line-clamp-2 max-w-3xl break-words text-sm leading-5 text-foreground/75"
                        title={title}
                    >
                        {title}
                        {duration != null && (
                            <span className="ms-2 whitespace-nowrap text-xs tabular-nums text-muted-foreground">
                                {formatDuration(duration)}
                            </span>
                        )}
                    </p>
                </div>

                <div className="flex shrink-0 items-center gap-1.5">
                    {canSharePlayLink && (
                        <Button
                            variant="outline"
                            size="sm"
                            className="hidden min-h-10 gap-1.5 px-3 sm:inline-flex"
                            onClick={onCopyShareLink}
                            aria-label={dict.result.sharePlayLink}
                        >
                            <Share2 className="h-4 w-4" aria-hidden="true" />
                            <span>{dict.result.sharePlayLink}</span>
                        </Button>
                    )}
                    {canSharePlayLink && (
                        <Button
                            variant="ghost"
                            size="icon"
                            className="h-10 w-10 sm:hidden"
                            onClick={onCopyShareLink}
                            aria-label={dict.result.sharePlayLink}
                        >
                            <Share2 className="h-4 w-4" aria-hidden="true" />
                        </Button>
                    )}
                    <Button
                        variant="ghost"
                        size="icon"
                        className="h-10 w-10"
                        onClick={onClose}
                        aria-label={dict.result.previewPlayerClose}
                    >
                        <X className="h-4 w-4" aria-hidden="true" />
                    </Button>
                </div>
            </div>
        </CardHeader>
    );
}
