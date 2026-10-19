import { useId, useState } from "react";
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

// The Cycls stars, traced from the identity's نجوم.svg: the solid one, and the one with a diamond cut out.
const SOLID = "M85.7 16.1C90.8 33.4 94.4 41.1 101.5 49.8C112.1 62.5 123.9 69.4 147.1 75.8C154.6 77.9 160.8 79.9 160.8 80.2C160.8 80.5 155.3 82.4 148.6 84.1C126 90.2 115.3 95.8 104.7 106.9C94.9 117.2 91.3 124.8 83.3 151.6C81.9 156.5 80.5 160.2 80.3 160.1C80.2 160 78.4 154.1 76.4 147.2C74.4 140.3 71.8 132.2 70.6 129.2C64.4 113.2 49.5 97.9 33.2 90.9C30.9 89.9 22.4 87.1 14.2 84.8C6 82.4 0 80.2 0.8 79.9C1.6 79.5 8.6 77.5 16.3 75.4C32.8 70.5 42.3 66 50.7 58.9C63.4 48.1 69.3 37.9 75.9 14.9C78.2 6.8 80.4 0.5 80.8 0.9C81.1 1.3 83.3 8.2 85.7 16.1Z";
const HOLLOW = "M93.6 37.8C96.9 44.6 99.5 48 106.3 54.8C117.3 65.7 124.8 69.7 145.9 75.9C154.7 78.5 161.2 80.9 160.4 81.2C159.6 81.5 152.6 83.5 144.9 85.8C128.5 90.5 120.6 94.1 112.2 100.9C105.1 106.6 101 111.2 96.2 118.8C91.4 126.5 90.7 128.3 85.4 146.3C82.7 155.1 80.4 161.6 80.1 160.8C79.8 160 77.5 152.4 74.9 143.9C72.4 135.5 69.3 126.5 68 123.9C61.8 111.8 49.3 99.4 37 93.4C33.1 91.5 23.3 88 15.2 85.7C7 83.3 0.4 81.2 0.4 80.9C0.4 80.5 6.6 78.6 14.2 76.5C36.7 70.2 50.1 62.5 59.9 50C66.5 41.8 70.9 32.3 75.5 16.3C77.7 8.6 79.8 1.6 80.1 0.8C80.4 0 82.6 6 85 14.3C87.4 22.5 91.3 33.1 93.6 37.8ZM77.6 55.7C74.1 61 59.5 75.4 54.6 78.3C52.8 79.4 51.4 80.5 51.4 80.8C51.4 81.1 53.1 82.2 55.1 83.3C60.2 86 74.5 100.4 77.9 106.2L80.6 110.9L83.9 106.1C87.8 100.5 101.2 87.1 106.7 83.5L110.4 81L105.7 77.5C99.8 73.1 86.4 59.6 83.1 54.6L80.7 50.9L77.6 55.7Z";

export function Star({ size, className, hollow }: { size: number; className?: string; hollow?: boolean }) {
  return (
    <svg viewBox="0 0 161 161" width={size} height={size} className={className} fill="currentColor">
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
      <GlowStar />
    </div>
  );
}

// The turning star: the brand's blue and orange, mixed into its ink, sweep through it over a faint glow of them.
function GlowStar() {
  const id = useId().replace(/\W/g, "");
  const mix = (c: string) => ({ stopColor: `color-mix(in oklab, ${c} 88%, currentColor)` });
  const sweep = <animateTransform attributeName="gradientTransform" type="translate" from="0" to="322" dur="3s" repeatCount="indefinite" />;
  return (
    <svg viewBox="0 0 161 161" width={16} height={16} className="animate-[spin_1.8s_linear_infinite] overflow-visible">
      <defs>
        <linearGradient id={`${id}i`} gradientUnits="userSpaceOnUse" x2="322" spreadMethod="repeat">
          <stop stopColor="currentColor" /><stop offset=".25" style={mix("#3171F6")} /><stop offset=".5" stopColor="currentColor" />
          <stop offset=".75" style={mix("#EF8733")} /><stop offset="1" stopColor="currentColor" />{sweep}
        </linearGradient>
        <linearGradient id={`${id}g`} gradientUnits="userSpaceOnUse" x2="322" spreadMethod="repeat">
          <stop stopColor="#3171F6" /><stop offset=".5" stopColor="#EF8733" /><stop offset="1" stopColor="#3171F6" />{sweep}
        </linearGradient>
        <filter id={`${id}b`} x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="22" /></filter>
      </defs>
      <path fillRule="evenodd" d={HOLLOW} fill={`url(#${id}g)`} filter={`url(#${id}b)`} opacity={0.2} transform="translate(80.5 80.5) scale(1.15) translate(-80.5 -80.5)" />
      <path fillRule="evenodd" d={HOLLOW} fill={`url(#${id}i)`} />
    </svg>
  );
}
