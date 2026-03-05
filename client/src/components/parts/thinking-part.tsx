import { useState } from "react";
import { cn } from "../../lib/utils";

export function ThinkingPart({ thinking }: { thinking: string }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      className={cn(
        "rounded-lg p-4 my-3 italic text-[var(--text-secondary)]",
        "bg-linear-to-br from-gray-100 to-gray-200 dark:from-gray-700 dark:to-gray-800",
        "border-l-3 border-[var(--accent)]",
      )}
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 text-sm font-medium text-[var(--accent)] cursor-pointer w-full text-left"
      >
        <svg
          className="w-4 h-4"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"
          />
        </svg>
        Thinking
        <svg
          className={cn(
            "w-3 h-3 transition-transform ml-auto",
            expanded && "rotate-180",
          )}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M19 9l-7 7-7-7"
          />
        </svg>
      </button>
      {expanded && (
        <div className="mt-2 text-sm whitespace-pre-wrap">{thinking}</div>
      )}
    </div>
  );
}
