import { Globe } from 'lucide-react';
import type { Dictionary } from '@/lib/i18n/types';
import { cn } from '@/lib/utils';
import { PlatformSupportGrid } from './PlatformSupportGrid';

interface PlatformGuideCardProps {
    dict: Pick<Dictionary, 'guide'>;
    className?: string;
}

export function PlatformGuideCard({ dict, className }: PlatformGuideCardProps) {
    return (
        <section className={cn('min-w-0 border-y py-3', className)}>
            <div className="flex items-center gap-2 text-sm font-semibold">
                <Globe className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                <h2>{dict.guide.platformSupport.title}</h2>
            </div>
            <div className="mt-3">
                <PlatformSupportGrid dict={dict} />
            </div>
        </section>
    );
}
