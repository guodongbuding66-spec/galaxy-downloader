import type { ComponentType, SVGProps } from 'react';
import { Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

interface MediaActionIconButtonProps {
    label: string;
    text?: string;
    icon: ComponentType<SVGProps<SVGSVGElement>>;
    variant?: 'outline' | 'secondary' | 'default';
    size?: 'xs' | 'sm';
    disabled?: boolean;
    loading?: boolean;
    className?: string;
    onClick: () => void;
}

export function MediaActionIconButton({
    label,
    text,
    icon: Icon,
    variant = 'outline',
    size = 'sm',
    disabled,
    loading,
    className,
    onClick,
}: MediaActionIconButtonProps) {
    return (
        <Button
            type="button"
            variant={variant}
            size={size}
            className={cn(
                'min-h-10 min-w-0 justify-center gap-1.5 whitespace-normal px-3 text-center leading-tight',
                className,
            )}
            disabled={disabled}
            onClick={onClick}
            aria-label={label}
            aria-busy={loading || undefined}
            title={label}
        >
            {loading ? (
                <Loader2 className="h-4 w-4 shrink-0 animate-spin" aria-hidden="true" />
            ) : (
                <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
            )}
            <span className="line-clamp-2">{text ?? label}</span>
        </Button>
    );
}
