import { memo } from "react";
import { cn } from "../../lib/utils";

// A callout is plain text, but a server that names the page you have to visit — Slack's "enable it
// here: <url>" — is only useful if the link is one click. Nothing else here is interpreted.
const URL_RE = /(https?:\/\/[^\s<>"')\]]+)/g;

function linkify(text: string) {
  return text.split(URL_RE).map((part, i) =>
    i % 2 === 1 ? (
      <a
        key={i}
        href={part}
        target="_blank"
        rel="noopener noreferrer"
        className="underline underline-offset-2 hover:opacity-80"
      >
        {part}
      </a>
    ) : (
      part
    ),
  );
}

const styles: Record<string, string> = {
  info: "border-l-blue-500 bg-blue-500/10",
  warning: "border-l-amber-500 bg-amber-500/10",
  error: "border-l-red-500 bg-red-500/10",
  success: "border-l-emerald-500 bg-emerald-500/10",
};

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
      <div className="whitespace-pre-wrap">{linkify(callout)}</div>
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
