import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
        <Card className={cn('overflow-hidden', className)}>
            <CardHeader className="p-5 pb-3 sm:p-6 sm:pb-4">
                <CardTitle className="flex items-center gap-2 text-base">
                    <Globe className="h-4 w-4 text-primary" />
                    {dict.guide.platformSupport.title}
                </CardTitle>
            </CardHeader>
            <CardContent className="p-5 pt-0 sm:p-6 sm:pt-0">
                <PlatformSupportGrid dict={dict} />
            </CardContent>
        </Card>
    );
} 
