import * as React from "react"
import { cn } from "../lib/utils"
import { Progress as ProgressPrimitive } from "radix-ui"

function Progress({
  className,
  value,
  ...props
}: React.ComponentProps<typeof ProgressPrimitive.Root>) {
  return (
    <ProgressPrimitive.Root
      data-slot="progress"
      className={cn(
        "relative h-2 w-full overflow-hidden rounded-full bg-primary/20",
        className
      )}
      {...props}
    >
      <ProgressPrimitive.Indicator
        data-slot="progress-indicator"
        // cycls-default-apps: scale from the inline-start edge so the bar fills right-to-left in Arabic
        className="h-full w-full flex-1 origin-left bg-primary transition-all rtl:origin-right"
        style={{ transform: `scaleX(${(value || 0) / 100})` }}
      />
    </ProgressPrimitive.Root>
  )
}

export { Progress }
