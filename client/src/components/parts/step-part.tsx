import { memo } from "react";
import { cn } from "../../lib/utils";

// While a tool call's input is still streaming we only have partial JSON; show
// a tail of it as a live "typing" preview until the resolved detail (path,
// command, …) arrives.
function preview(args?: string) {
  if (!args) return "";
  const tail = args.length > 48 ? "…" + args.slice(-48) : args;
  return tail.replace(/\s+/g, " ").trim();
}

export const StepPart = memo(function StepPart({
  step,
  args,
  toolName,
  isStreaming,
}: {
  step: string;
  args?: string;
  toolName?: string;
  isStreaming?: boolean;
}) {
  const detail = step || preview(args);
  return (
    <div className="flex items-center gap-2 py-1 text-sm text-muted-foreground">
      <div
        className={cn(
          "flex size-5 shrink-0 items-center justify-center rounded-full border border-border",
          isStreaming ? "border-accent" : "bg-accent/10",
        )}
      >
        {isStreaming ? (
          <span className="block size-1.5 rounded-full bg-accent animate-pulse" />
        ) : (
          <svg
            className="size-3 text-accent"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
          </svg>
        )}
      </div>
      <span className="font-mono text-[13px] truncate">
        {toolName ? (
          <>
            <span className="font-semibold text-foreground">{toolName}</span>
            {detail && (
              <>
                <span className="text-foreground">(</span>
                {detail}
                <span className="text-foreground">)</span>
              </>
            )}
          </>
        ) : (
          detail
        )}
      </span>
    </div>
  );
});
