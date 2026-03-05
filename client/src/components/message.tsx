import { useState } from "react";
import { motion } from "framer-motion";
import type { Part, Message } from "../hooks/use-chat";
import { TextPart } from "./parts/text-part";
import { ThinkingPart } from "./parts/thinking-part";
import { CodePart } from "./parts/code-part";
import { TablePart } from "./parts/table-part";
import { CalloutPart } from "./parts/callout-part";
import { ImagePart } from "./parts/image-part";
import { StepPart } from "./parts/step-part";
import { cn } from "../lib/utils";

function renderPart(part: Part, index: number, isStreaming?: boolean) {
  switch (part.type) {
    case "text":
      return <TextPart key={index} text={part.text || ""} />;
    case "thinking":
      return (
        <ThinkingPart
          key={index}
          thinking={part.thinking || ""}
        />
      );
    case "code":
      return (
        <CodePart key={index} code={part.code || ""} language={part.language} />
      );
    case "table":
      return <TablePart key={index} headers={part.headers} rows={part.rows} />;
    case "callout":
      return (
        <CalloutPart
          key={index}
          callout={part.callout || ""}
          style={part.style}
          title={part.title}
        />
      );
    case "image":
      return (
        <ImagePart
          key={index}
          src={part.src || ""}
          alt={part.alt}
          caption={part.caption}
        />
      );
    case "step":
      return (
        <StepPart
          key={index}
          step={part.step || ""}
          toolName={part.tool_name}
          isStreaming={isStreaming}
        />
      );
    case "status":
      return (
        <div
          key={index}
          className="text-sm text-muted-foreground italic flex items-center gap-2 py-1"
        >
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
          {part.status}
        </div>
      );
    default:
      return null;
  }
}

export function MessageBubble({
  message,
  isStreaming,
}: {
  message: Message;
  isStreaming?: boolean;
}) {
  const [copied, setCopied] = useState(false);

  if (message.role === "user") {
    return (
      <div className="flex w-full max-w-3xl items-start gap-4 px-6 pb-2 justify-end">
        <div dir="auto" className="rounded-3xl bg-secondary text-secondary-foreground px-4 py-2.5 max-w-[80%]">
          {message.content}
        </div>
      </div>
    );
  }

  const parts = (message.parts || []).filter((p) => p.type !== "session_id");
  const isEmpty = parts.length === 0;

  const copyAll = () => {
    const text = parts
      .filter((p) => p.type === "text")
      .map((p) => p.text)
      .join("");
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="group flex w-full max-w-3xl items-start gap-4 px-6 pb-2">
      <div className="relative flex min-w-0 flex-1 flex-col gap-1">
        {isEmpty && isStreaming && <Loader />}

        {parts.map((part, i) => renderPart(part, i, isStreaming))}

        {/* Actions */}
        {!isEmpty && !isStreaming && (
          <div
            className={cn(
              "flex gap-0 -ml-2 opacity-0 transition-opacity group-hover:opacity-100",
            )}
          >
            <button
              onClick={copyAll}
              className="hover:bg-secondary text-muted-foreground hover:text-foreground flex size-7 items-center justify-center rounded-full transition cursor-pointer"
              aria-label="Copy"
              type="button"
            >
              {copied ? (
                <svg
                  className="w-3.5 h-3.5"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M5 13l4 4L19 7"
                  />
                </svg>
              ) : (
                <svg
                  className="w-3.5 h-3.5"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"
                  />
                </svg>
              )}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

const STAR_PATH = "M 5.248 0 L 5.734 1.654 C 6.164 3.153 7.345 4.33 8.844 4.765 L 10.496 5.241 L 8.844 5.718 C 7.345 6.152 6.164 7.329 5.734 8.829 L 5.248 10.496 L 4.762 8.843 C 4.332 7.343 3.152 6.166 1.652 5.732 L 0 5.255 L 1.652 4.779 C 3.152 4.344 4.332 3.167 4.762 1.668 L 5.248 0 Z";
const SMALL_STAR_PATH = "M 17.359 13.159 C 17.493 13.671 18.909 15.02 19.38 15.192 C 18.909 15.31 17.516 16.704 17.359 17.226 C 17.225 16.714 15.89 15.308 15.338 15.192 C 15.89 14.962 17.211 13.671 17.359 13.159 Z";

function Loader() {
  return (
    <div className="flex items-center py-3">
      <svg viewBox="-1 -1 22 19" className="h-7 text-foreground/60">
        <motion.path
          d={STAR_PATH}
          fill="currentColor"
          animate={{ scale: [1, 0.5, 1], opacity: [1, 0.2, 1] }}
          transition={{ duration: 0.9, repeat: Infinity, ease: "easeInOut" }}
          style={{ transformOrigin: "5.248px 5.248px" }}
        />
        <motion.path
          d={SMALL_STAR_PATH}
          fill="none"
          stroke="currentColor"
          strokeWidth={0.6}
          animate={{ scale: [0.5, 1, 0.5], opacity: [0.2, 1, 0.2] }}
          transition={{ duration: 0.9, repeat: Infinity, ease: "easeInOut" }}
          style={{ transformOrigin: "17.359px 15.192px" }}
          transform="translate(-3 -3)"
        />
      </svg>
    </div>
  );
}
