import Image from 'next/image';
import type { Dictionary } from '@/lib/i18n/types';
import { cn } from '@/lib/utils';
import { getPlatformSupportItems } from './platform-support';

interface PlatformSupportGridProps {
    dict: Pick<Dictionary, 'guide'>;
}

export function PlatformSupportGrid({ dict }: PlatformSupportGridProps) {
    const items = getPlatformSupportItems(dict);

    return (
        <div className="grid overflow-hidden border-y bg-border sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {items.map((item) => (
                <div
                    key={item.key}
                    className="group flex min-h-11 min-w-0 items-center gap-2.5 bg-background px-2.5 py-2 transition-colors hover:bg-accent/45"
                >
                    <div
                        className={cn(
                            'relative flex h-8 w-8 shrink-0 items-center justify-center rounded-md border bg-[hsl(var(--surface-subtle))]',
                            item.visual.frameClassName,
                        )}
                    >
                        {item.visual.src && item.visual.darkSrc ? (
                            <>
                                <Image src={item.visual.src} alt="" aria-hidden width={14} height={14} unoptimized className={cn('h-3.5 w-3.5 object-contain dark:hidden', item.visual.iconClassName)} />
                                <Image src={item.visual.darkSrc} alt="" aria-hidden width={14} height={14} unoptimized className={cn('hidden h-3.5 w-3.5 object-contain dark:block', item.visual.iconClassName)} />
                            </>
                        ) : item.visual.src ? (
                            <Image src={item.visual.src} alt="" aria-hidden width={14} height={14} unoptimized className={cn('h-3.5 w-3.5 object-contain', item.visual.iconClassName)} />
                        ) : (
                            <span className="text-[10px] font-semibold uppercase text-foreground/80">
                                {item.visual.fallbackLabel || item.name.slice(0, 2)}
                            </span>
                        )}
                        {item.visual.badgeLabel ? (
                            <span className={cn('absolute -right-1 -top-1 rounded-sm border bg-background px-1 py-0.5 text-[8px] font-semibold leading-none', item.visual.badgeClassName)}>
                                {item.visual.badgeLabel}
                            </span>
                        ) : null}
                    </div>
                    <p className="min-w-0 truncate text-xs font-semibold leading-5 text-foreground" title={item.name}>{item.name}</p>
                </div>
            ))}
        </div>
    );
}
