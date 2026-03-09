import { cn } from "../../lib/utils";

const styles: Record<string, string> = {
  info: "border-l-blue-500 bg-blue-500/10",
  warning: "border-l-amber-500 bg-amber-500/10",
  error: "border-l-red-500 bg-red-500/10",
  success: "border-l-emerald-500 bg-emerald-500/10",
};

import { memo } from "react";

export const CalloutPart = memo(function CalloutPart({
  callout,
  style = "info",
  title,
  onRetry,
}: {
  callout: string;
  style?: string;
  title?: string;
  onRetry?: () => void;
}) {
  return (
    <div
      className={cn(
        "border-l-4 rounded-r-lg p-4 my-3 text-sm",
        styles[style] || styles.info,
      )}
    >
      {title && <div className="font-semibold mb-1">{title}</div>}
      <div>{callout}</div>
      {onRetry && style === "error" && (
        <button
          onClick={onRetry}
          type="button"
          className="mt-2 px-3 py-1 text-xs font-medium rounded-md bg-red-500/20 hover:bg-red-500/30 text-red-700 dark:text-red-300 transition-colors cursor-pointer"
        >
          Retry
        </button>
      )}
    </div>
  );
});
