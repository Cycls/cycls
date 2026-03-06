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

function groupParts(parts: Part[]) {
  const groups: { type: string; items: Part[]; startIndex: number }[] = [];
  for (let i = 0; i < parts.length; i++) {
    const last = groups[groups.length - 1];
    if (parts[i].type === "step" && last?.type === "step") {
      last.items.push(parts[i]);
    } else {
      groups.push({ type: parts[i].type, items: [parts[i]], startIndex: i });
    }
  }
  return groups;
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
    const attachments = message.attachments;
    return (
      <div className="flex w-full max-w-3xl items-start gap-4 px-6 pb-2 justify-end">
        <div className="flex flex-col items-end gap-2 max-w-[80%]">
          {attachments && attachments.length > 0 && (
            <div className="flex flex-row gap-2 flex-wrap justify-end">
              {attachments.map((att, i) => (
                <a
                  key={att.name + i}
                  href={att.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="border border-border bg-background hover:bg-secondary/50 flex items-center gap-3 rounded-2xl p-2 pr-3 transition-colors cursor-pointer"
                >
                  <div className="bg-secondary flex size-10 shrink-0 items-center justify-center overflow-hidden rounded-lg">
                    {att.type.startsWith("image/") ? (
                      <img
                        src={att.url}
                        alt={att.name}
                        className="size-full object-cover"
                      />
                    ) : (
                      <span className="text-[10px] font-medium text-muted-foreground uppercase">
                        {att.name.split(".").pop()}
                      </span>
                    )}
                  </div>
                  <div className="flex flex-col overflow-hidden min-w-0">
                    <span className="truncate text-xs font-medium text-foreground max-w-[120px]">{att.name}</span>
                    <span className="text-xs text-muted-foreground">
                      {(att.size / 1024).toFixed(1)} kB
                    </span>
                  </div>
                </a>
              ))}
            </div>
          )}
          <div dir="auto" className="rounded-3xl bg-secondary text-secondary-foreground px-4 py-2.5">
            {message.content}
          </div>
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

        {groupParts(parts).map((group, gi) =>
          group.type === "step" ? (
            <div key={gi} className="my-3 flex flex-col">
              {group.items.map((part, i) => renderPart(part, group.startIndex + i, isStreaming))}
            </div>
          ) : (
            group.items.map((part, i) => renderPart(part, group.startIndex + i, isStreaming))
          )
        )}

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

function Star({ size, className }: { size: number; className?: string }) {
  return (
    <svg viewBox="0 0 10.5 10.5" width={size} height={size} className={className} fill="currentColor">
      <path d="M 5.248 0 L 5.734 1.654 C 6.164 3.153 7.345 4.33 8.844 4.765 L 10.496 5.241 L 8.844 5.718 C 7.345 6.152 6.164 7.329 5.734 8.829 L 5.248 10.496 L 4.762 8.843 C 4.332 7.343 3.152 6.166 1.652 5.732 L 0 5.255 L 1.652 4.779 C 3.152 4.344 4.332 3.167 4.762 1.668 L 5.248 0 Z" />
    </svg>
  );
}

function Loader() {
  return (
    <div className="flex items-center gap-1.5 py-3">
      <motion.div
        animate={{ scale: [1, 0.5, 1], opacity: [1, 0.2, 1] }}
        transition={{ duration: 0.9, repeat: Infinity, ease: "easeInOut" }}
      >
        <Star size={12} className="text-foreground/60" />
      </motion.div>
      <motion.div
        animate={{ scale: [0.5, 1, 0.5], opacity: [0.2, 1, 0.2] }}
        transition={{ duration: 0.9, repeat: Infinity, ease: "easeInOut" }}
      >
        <Star size={8} className="text-foreground/60" />
      </motion.div>
    </div>
  );
}
