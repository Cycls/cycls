import { useState } from "react";
import type { Part, Message, Source } from "../hooks/use-chat";
import { TextPart } from "./parts/text-part";
import { ThinkingPart } from "./parts/thinking-part";
import { CodePart } from "./parts/code-part";
import { TablePart } from "./parts/table-part";
import { CalloutPart } from "./parts/callout-part";
import { ImagePart } from "./parts/image-part";
import { StepPart } from "./parts/step-part";
import { StepGroup } from "./parts/step-group";
import { FilePart } from "./parts/file-part";
import { SelectionChip } from "./selection-chip";
import { SourcesPart } from "./parts/sources-part";
import { AttachmentBody } from "./attachment-body";
import { Icon } from "./icon";
import { cn } from "../lib/utils";
import { urlKey } from "./parts/sources-part";
import { useMemo } from "react";
import { t } from "../lib/i18n";

function renderPart(part: Part, index: number, isStreaming?: boolean, onRetry?: () => void, onOpenFile?: (path: string) => void, sources?: Map<string, Source>) {
  switch (part.type) {
    case "text":
      return <TextPart key={index} text={part.text || ""} onOpenFile={onOpenFile} sources={sources} />;
    case "thinking":
      return (
        <ThinkingPart
          key={index}
          thinking={part.thinking || ""}
          isStreaming={isStreaming}
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
          onRetry={part.style === "error" ? onRetry : undefined}
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
    case "sources":
      return <SourcesPart key={index} sources={part.sources || []} />;
    case "step":
      return (
        <StepPart
          key={index}
          step={part.step || ""}
          toolName={part.tool_name}
          isStreaming={isStreaming}
          args={part.args}
          at={part.at}
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

// Successful canvas calls are deliverables — they render as file cards and
// must never fold into a step group.
function groupKind(p: Part) {
  if (p.type === "step" && p.tool_name === "Canvas" && p.step && p.ok !== false) return "file";
  return p.type;
}

function groupParts(parts: Part[]) {
  const groups: { kind: string; items: Part[]; startIndex: number }[] = [];
  for (let i = 0; i < parts.length; i++) {
    const kind = groupKind(parts[i]);
    const last = groups[groups.length - 1];
    if (kind === "step" && last?.kind === "step") {
      last.items.push(parts[i]);
    } else {
      groups.push({ kind, items: [parts[i]], startIndex: i });
    }
  }
  return groups;
}

export function MessageBubble({
  message,
  isStreaming,
  onRetry,
  onRegenerate,
  onOpenFile,
}: {
  message: Message;
  isStreaming?: boolean;
  onRetry?: () => void;
  // Only passed for the last assistant message — regenerating an earlier one
  // would mean truncating the transcript back to it, which the API doesn't do.
  onRegenerate?: () => void;
  onOpenFile?: (path: string) => void;
}) {
  const [copied, setCopied] = useState(false);

  if (message.role === "user") {
    const attachments = message.attachments;
    return (
      <div className="flex w-full max-w-3xl items-start gap-4 px-6 pb-2 justify-end">
        <div className="flex flex-col items-end gap-2 max-w-[80%]">
          {message.selection && <SelectionChip selection={message.selection} />}
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
                  <AttachmentBody attachment={att} />
                </a>
              ))}
            </div>
          )}
          <div dir="auto" className="rounded-3xl bg-secondary text-secondary-foreground px-4 py-2.5 whitespace-pre-wrap break-words">
            {message.content}
          </div>
        </div>
      </div>
    );
  }

  const parts = (message.parts || [])
    .filter((p) => p.type !== "chat_id")
    // Collapse consecutive canvas cards for the same file (retries) into one.
    .filter((p, i, all) => {
      if (p.type !== "step" || p.tool_name !== "Canvas") return true;
      const next = all[i + 1];
      return !(next?.type === "step" && next.tool_name === "Canvas" && next.step === p.step);
    });
  // `sources` parts don't render where they land — one chip row per search
  // repeated the same domains through the turn. They're merged and deduped
  // into a single row at the END of the message instead, which is also the
  // only thing that guarantees provenance is visible: citing inline is the
  // model's choice, and a turn where it searches but doesn't cite would
  // otherwise show no sources at all.
  //
  // `suggest` and `ask` drive the composer, not the transcript. Their step
  // line restated a chip or a card the user is already looking at, and padded
  // the "N steps" count with work that isn't work.
  // A search's results ride into its own step row, threaded by the id of the call that ran them, and
  // expand under the query there. The deduped chip row at the end of the turn stays: provenance can't
  // depend on the reader opening a step.
  const byCall = new Map<string, Source[]>();
  for (const p of parts) if (p.type === "sources" && p.id && p.sources?.length) byCall.set(p.id, p.sources);
  const rendered = parts
    .filter((p) => p.type !== "sources" && !(p.type === "step" && (p.tool_name === "Suggest" || p.tool_name === "Ask")))
    .map((p) => (p.type === "step" && p.id && byCall.has(p.id) ? { ...p, sources: byCall.get(p.id) } : p));
  const isEmpty = rendered.length === 0;

  // Every result this turn's searches returned, keyed for link lookup. `parts`
  // is rebuilt on every streamed token, so the memo keys on the URLs instead —
  // a churning map identity would re-render every markdown block per token.
  const sourceKey = parts
    .filter((p) => p.type === "sources")
    .map((p) => (p.sources || []).map((s) => s.url).join(","))
    .join("|");
  const sourceIndex = useMemo(() => {
    if (!sourceKey) return undefined;
    const map = new Map<string, Source>();
    for (const p of parts) {
      if (p.type !== "sources") continue;
      for (const s of p.sources || []) if (s.url) map.set(urlKey(s.url), s);
    }
    return map.size ? map : undefined;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceKey]);

  // Deduped by `urlKey`, so the same article returned by two searches is one
  // chip. Held back until the turn ends — appended live it would shunt itself
  // down the page on every streamed token.
  const allSources = useMemo(() => (sourceIndex ? [...sourceIndex.values()] : []), [sourceIndex]);

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

        {groupParts(rendered).map((group, gi, all) => {
          if (group.kind === "step")
            return <StepGroup key={gi} items={group.items} live={isStreaming && gi === all.length - 1} />;
          if (group.kind === "file")
            return <FilePart key={gi} path={group.items[0].step || ""} onOpen={onOpenFile} />;
          return group.items.map((part, i) =>
            renderPart(part, group.startIndex + i,
              isStreaming && group.startIndex + i === rendered.length - 1, onRetry, onOpenFile, sourceIndex));
        })}

        {!isStreaming && allSources.length > 0 && <SourcesPart sources={allSources} />}

        {/* Actions */}
        {!isEmpty && !isStreaming && (
          <div
            className={cn(
              "flex gap-0 -ml-2 opacity-100 sm:opacity-0 transition-opacity sm:group-hover:opacity-100",
            )}
          >
            <button
              onClick={copyAll}
              className="hover:bg-secondary text-muted-foreground hover:text-foreground flex size-7 items-center justify-center rounded-full transition cursor-pointer"
              aria-label="Copy"
              type="button"
            >
              <Icon name={copied ? "check" : "copy"} className="w-3.5 h-3.5" />
            </button>
            {onRegenerate && (
              <button
                onClick={onRegenerate}
                className="hover:bg-secondary text-muted-foreground hover:text-foreground flex size-7 items-center justify-center rounded-full transition cursor-pointer"
                aria-label={t("regenerate")}
                title={t("regenerate")}
                type="button"
              >
                <Icon name="refresh" className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// The Cycls logo's two stars, their paths as the logo draws them: the solid one, and the one with a star cut out.
const SOLID = "M12.0452 3.47365C12.9493 6.62348 15.4284 9.0963 18.5783 10.0089L22.0488 11.0096L18.5783 12.0106C15.4284 12.9232 12.9493 15.396 12.0452 18.5458L11.0245 22.0488L10.0036 18.5752C9.09945 15.4254 6.62051 12.9525 3.47072 12.0399L0 11.0392L3.47072 10.0382C6.62048 9.12563 9.09945 6.65294 10.0036 3.50318L11.0245 0L12.0452 3.47365Z";
const HOLLOW = "M37.5137 24.2766C38.4311 27.4728 40.9467 29.9819 44.1428 30.9079L47.6645 31.9235L44.1428 32.9391C40.9467 33.8651 38.4311 36.3742 37.5137 39.5704L36.4779 43.125L35.4421 39.6003C34.5247 36.4041 32.0092 33.8949 28.813 32.9689L25.2915 31.9534L28.813 30.9378C32.0092 30.0118 34.5247 27.5027 35.4421 24.3065L36.4779 20.7519L37.5137 24.2766ZM36.5076 27.6818C36.1965 28.7572 33.4214 31.4699 32.262 31.9534C33.4214 32.1974 36.226 35.1495 36.5076 36.2248C36.8369 35.129 39.764 32.2019 40.753 31.9534C39.764 31.5917 36.7892 28.7572 36.5076 27.6818Z";

function Star({ size, className, hollow }: { size: number; className?: string; hollow?: boolean }) {
  return (
    <svg viewBox={hollow ? "25.29 20.75 22.38 22.38" : "0 0 22.05 22.05"} width={size} height={size} className={className} fill="currentColor">
      <path fillRule="evenodd" d={hollow ? HOLLOW : SOLID} />
    </svg>
  );
}

// Three Cycls stars while the reply has not begun: two still, the hollow third turning.
function Loader() {
  return (
    <div className="flex items-center gap-0.5 py-3 text-foreground/70">
      <Star size={16} />
      <Star size={16} />
      <Star size={16} hollow className="animate-[spin_1.8s_linear_infinite]" />
    </div>
  );
}
