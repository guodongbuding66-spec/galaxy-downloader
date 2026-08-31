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
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
            {items.map((item) => (
                <div key={item.key} className="group flex min-w-0 items-center gap-2.5 rounded-xl border border-border/70 bg-background/70 px-3 py-2.5 shadow-sm transition-[border-color,background-color,box-shadow,transform] duration-150 hover:-translate-y-0.5 hover:border-primary/30 hover:bg-primary/[0.025] hover:shadow-md motion-reduce:transform-none">
                    <div
                        className={cn(
                            'relative flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border bg-card',
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
                            <span className="text-[9px] font-semibold uppercase text-foreground/80">
                                {item.visual.fallbackLabel || item.name.slice(0, 2)}
                            </span>
                        )}
                        {item.visual.badgeLabel ? (
                            <span className={cn('absolute -right-1 -top-1 rounded-full px-1 py-0.5 text-[7px] font-semibold leading-none shadow-sm', item.visual.badgeClassName)}>
                                {item.visual.badgeLabel}
                            </span>
                        ) : null}
                    </div>
                    <p className="min-w-0 truncate text-sm font-semibold leading-5 text-foreground">{item.name}</p>
                </div>
            ))}
        </div>
    );
}
