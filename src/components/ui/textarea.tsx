import * as React from "react"

import { cn } from "@/lib/utils"

const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.ComponentProps<"textarea">
>(({ className, ...props }, ref) => {
  return (
    <textarea
      className={cn(
        "ui-target ui-field flex min-h-[64px] w-full rounded-lg border border-input bg-background px-3 py-2.5 text-base leading-5 text-foreground shadow-[inset_0_1px_0_hsl(var(--shadow-color)/0.018)] outline-none placeholder:text-muted-foreground/90 disabled:cursor-not-allowed disabled:bg-muted/55 disabled:opacity-60 md:text-sm",
        className
      )}
      ref={ref}
      {...props}
    />
  )
})
Textarea.displayName = "Textarea"

export { Textarea }
