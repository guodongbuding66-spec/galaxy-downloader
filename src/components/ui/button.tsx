import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "ui-pressable inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl text-sm font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default:
          "bg-primary text-primary-foreground shadow-[0_1px_2px_hsl(var(--shadow-color)/0.08),0_7px_18px_hsl(var(--primary)/0.18)] hover:bg-primary/94 hover:shadow-[0_2px_4px_hsl(var(--shadow-color)/0.08),0_10px_24px_hsl(var(--primary)/0.22)] active:shadow-[0_1px_2px_hsl(var(--shadow-color)/0.08),0_3px_9px_hsl(var(--primary)/0.14)]",
        destructive:
          "bg-destructive text-destructive-foreground shadow-[0_1px_2px_hsl(var(--shadow-color)/0.08),0_6px_16px_hsl(var(--destructive)/0.16)] hover:bg-destructive/92",
        outline:
          "border border-input bg-card text-foreground shadow-[0_1px_2px_hsl(var(--shadow-color)/0.05)] hover:border-primary/25 hover:bg-accent/70 hover:text-accent-foreground",
        secondary:
          "bg-secondary text-secondary-foreground shadow-[0_1px_2px_hsl(var(--shadow-color)/0.05)] hover:bg-secondary/72",
        ghost: "shadow-none hover:bg-accent/70 hover:text-accent-foreground",
        link: "rounded-md text-primary underline-offset-4 shadow-none hover:underline",
      },
      size: {
        default: "h-10 px-4 py-2",
        xs: "h-8 rounded-lg px-2.5 text-[11px] [&_svg]:size-3.5",
        sm: "h-9 px-3 text-xs",
        lg: "h-11 px-6 sm:px-8",
        icon: "h-10 w-10",
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
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button"
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    )
  }
)
Button.displayName = "Button"

export { Button, buttonVariants }
