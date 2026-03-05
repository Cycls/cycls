import { cn } from "../../lib/utils";

const styles: Record<string, string> = {
  info: "border-l-blue-500 bg-blue-50 dark:bg-blue-950",
  warning: "border-l-amber-500 bg-amber-50 dark:bg-amber-950",
  error: "border-l-red-500 bg-red-50 dark:bg-red-950",
  success: "border-l-emerald-500 bg-emerald-50 dark:bg-emerald-950",
};

const icons: Record<string, string> = {
  info: "M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z",
  warning:
    "M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z",
  error: "M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z",
  success: "M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z",
};

export function CalloutPart({
  callout,
  style = "info",
  title,
}: {
  callout: string;
  style?: string;
  title?: string;
}) {
  return (
    <div
      className={cn(
        "border-l-4 rounded-r-lg p-4 my-3",
        styles[style] || styles.info,
      )}
    >
      <div className="flex items-start gap-2">
        <svg
          className="w-5 h-5 mt-0.5 shrink-0"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d={icons[style] || icons.info}
          />
        </svg>
        <div>
          {title && <div className="font-semibold mb-1">{title}</div>}
          <div className="text-sm">{callout}</div>
        </div>
      </div>
    </div>
  );
}
