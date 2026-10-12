import { Check, Heart, Info } from 'lucide-react';
import type { Dictionary } from '@/lib/i18n/types';

interface FreeSupportCardProps {
    dict: Pick<Dictionary, 'freeSupport'>;
}

export function FreeSupportCard({ dict }: FreeSupportCardProps) {
    const features = [
        dict.freeSupport.features.freeToUse,
        dict.freeSupport.features.noRegistration,
        dict.freeSupport.features.unlimitedDownloads,
    ];

    return (
        <section className="min-w-0 border-t pt-3">
            <div className="flex items-center gap-2 text-sm font-semibold">
                <Heart className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                <h2>{dict.freeSupport.title}</h2>
            </div>

            <ul className="mt-2 divide-y">
                {features.map((feature) => (
                    <li key={feature} className="flex min-h-9 items-start gap-2.5 py-2 text-xs leading-5">
                        <Check className="mt-0.5 h-4 w-4 shrink-0 text-[hsl(var(--success))]" aria-hidden="true" />
                        <span>{feature}</span>
                    </li>
                ))}
            </ul>

            <div className="mt-1 flex items-start gap-2.5 border-t pt-2.5 text-xs leading-5 text-muted-foreground">
                <Info className="mt-0.5 h-4 w-4 shrink-0 text-[hsl(var(--info))]" aria-hidden="true" />
                <div className="min-w-0 space-y-0.5">
                    <p>{dict.freeSupport.revenue.adsSupport}</p>
                    <p>{dict.freeSupport.revenue.serverCosts}</p>
                </div>
            </div>
        </section>
    );
}
