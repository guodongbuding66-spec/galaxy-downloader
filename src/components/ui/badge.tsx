import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex min-h-5 items-center rounded-md border border-transparent px-2 py-0.5 text-[11px] font-medium leading-4 tracking-[-0.005em] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/45 focus-visible:ring-offset-2 focus-visible:ring-offset-background",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground",
        secondary: "border-border/45 bg-secondary text-secondary-foreground",
        destructive: "bg-destructive text-destructive-foreground",
        outline: "border-border/85 bg-background text-muted-foreground",
        success: "border-[hsl(var(--success)/0.2)] bg-[hsl(var(--success)/0.1)] text-[hsl(var(--success))]",
        warning: "border-[hsl(var(--warning)/0.22)] bg-[hsl(var(--warning)/0.1)] text-[hsl(var(--warning))]",
        info: "border-[hsl(var(--info)/0.2)] bg-[hsl(var(--info)/0.1)] text-[hsl(var(--info))]",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  )
}

export { Badge, badgeVariants }
