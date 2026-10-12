import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "ui-target ui-pressable inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg border border-transparent text-sm font-medium tracking-[-0.01em] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/45 focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-45 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default:
          "bg-primary text-primary-foreground shadow-[0_1px_2px_hsl(var(--shadow-color)/0.12)] hover:bg-primary/92 hover:shadow-[0_2px_5px_hsl(var(--shadow-color)/0.14)]",
        destructive:
          "bg-destructive text-destructive-foreground shadow-[0_1px_2px_hsl(var(--shadow-color)/0.1)] hover:bg-destructive/92",
        outline:
          "border-border/90 bg-background text-foreground shadow-[0_1px_1px_hsl(var(--shadow-color)/0.025)] hover:border-foreground/20 hover:bg-[hsl(var(--surface-hover))]",
        secondary:
          "border-border/55 bg-secondary text-secondary-foreground hover:border-border hover:bg-[hsl(var(--surface-hover))]",
        ghost:
          "text-foreground hover:bg-[hsl(var(--surface-hover))] hover:text-accent-foreground",
        link:
          "rounded-md text-foreground underline-offset-4 hover:text-foreground/75 hover:underline",
      },
      size: {
        default: "h-10 px-4 py-2",
        xs: "h-8 rounded-md px-2.5 text-xs [&_svg]:size-3.5",
        sm: "h-9 px-3 text-xs",
        lg: "h-11 px-5 sm:px-6",
        icon: "h-10 w-10 p-0",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, type, ...props }, ref) => {
    const Comp = asChild ? Slot : "button"
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...(!asChild ? { type: type ?? "button" } : {})}
        {...props}
      />
    )
  }
)
Button.displayName = "Button"

export { Button, buttonVariants }
