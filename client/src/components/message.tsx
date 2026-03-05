import type { Part, Message } from "../hooks/use-chat";
import { TextPart } from "./parts/text-part";
import { ThinkingPart } from "./parts/thinking-part";
import { CodePart } from "./parts/code-part";
import { TablePart } from "./parts/table-part";
import { CalloutPart } from "./parts/callout-part";
import { ImagePart } from "./parts/image-part";
import { cn } from "../lib/utils";

function renderPart(part: Part, index: number) {
  switch (part.type) {
    case "text":
      return <TextPart key={index} text={part.text || ""} />;
    case "thinking":
      return <ThinkingPart key={index} thinking={part.thinking || ""} />;
    case "code":
      return (
        <CodePart key={index} code={part.code || ""} language={part.language} />
      );
    case "table":
      return (
        <TablePart key={index} headers={part.headers} rows={part.rows} />
      );
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
    case "status":
      return (
        <div
          key={index}
          className="text-sm text-[var(--text-secondary)] italic my-2 flex items-center gap-2"
        >
          <span className="inline-block w-2 h-2 rounded-full bg-[var(--accent)] animate-pulse" />
          {part.status}
        </div>
      );
    case "session_id":
      return null;
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
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="bg-[var(--accent)] text-white rounded-2xl rounded-br-sm px-4 py-2.5 max-w-[80%]">
          {message.content}
        </div>
      </div>
    );
  }

  const parts = (message.parts || []).filter((p) => p.type !== "session_id");
  const isEmpty = parts.length === 0;

  return (
    <div className="flex justify-start">
      <div
        className={cn(
          "bg-[var(--bg-secondary)] rounded-2xl rounded-bl-sm px-4 py-2.5 max-w-[80%] min-w-[60px]",
          isStreaming && "streaming border-l-2",
        )}
      >
        {isEmpty && isStreaming && (
          <div className="flex gap-1 py-2">
            <span className="w-2 h-2 rounded-full bg-[var(--text-secondary)] animate-bounce" />
            <span
              className="w-2 h-2 rounded-full bg-[var(--text-secondary)] animate-bounce"
              style={{ animationDelay: "0.15s" }}
            />
            <span
              className="w-2 h-2 rounded-full bg-[var(--text-secondary)] animate-bounce"
              style={{ animationDelay: "0.3s" }}
            />
          </div>
        )}
        {parts.map((part, i) => renderPart(part, i))}
      </div>
    </div>
  );
}
