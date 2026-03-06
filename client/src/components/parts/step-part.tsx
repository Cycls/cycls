import { cn } from "../../lib/utils";

export function StepPart({
  step,
  toolName,
  isStreaming,
}: {
  step: string;
  toolName?: string;
  isStreaming?: boolean;
}) {
  return (
    <div className="flex items-center gap-2 py-1 text-sm text-muted-foreground">
      <div
        className={cn(
          "flex size-5 shrink-0 items-center justify-center rounded-full border border-border",
          isStreaming
            ? "border-accent"
            : "bg-accent/10",
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
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2.5}
              d="M5 13l4 4L19 7"
            />
          </svg>
        )}
      </div>
      <span className="font-mono text-[13px] truncate">
        {toolName ? (
          <>
            <span className="font-semibold text-foreground">{toolName}</span>
            <span className="text-foreground">(</span>
            {step}
            <span className="text-foreground">)</span>
          </>
        ) : (
          step
        )}
      </span>
    </div>
  );
}
