import * as React from "react"

import { cn } from "@/lib/utils"

const Input = React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>(
  ({ className, type, ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(
          "ui-target ui-field flex h-10 w-full rounded-lg border border-input bg-background px-3 py-2 text-base text-foreground shadow-[inset_0_1px_0_hsl(var(--shadow-color)/0.018)] outline-none file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground placeholder:text-muted-foreground/90 disabled:cursor-not-allowed disabled:bg-muted/55 disabled:opacity-60 md:text-sm",
          className
        )}
        ref={ref}
        {...props}
      />
    )
  }
)
Input.displayName = "Input"

export { Input }
