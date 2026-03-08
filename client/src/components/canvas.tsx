import { useState } from "react";
import { TextPart } from "./parts/text-part";
import { CodeBlockCode } from "./parts/code-block";

const CODE_TYPES = new Set([
  "python", "javascript", "typescript", "java", "go", "rust", "c", "cpp",
  "ruby", "php", "swift", "kotlin", "scala", "shell", "bash", "sql",
  "json", "yaml", "toml", "xml", "css", "scss",
]);

export interface CanvasData {
  title: string;
  content: string;
  contentType: string;
  src?: string;
}

export function Canvas({
  title,
  content,
  contentType,
  src,
  onClose,
}: CanvasData & { onClose: () => void }) {
  const [tab, setTab] = useState<"rendered" | "raw">("rendered");
  const [copied, setCopied] = useState(false);

  const isCode = CODE_TYPES.has(contentType);
  const hasTabs = contentType === "markdown" || contentType === "html" || contentType === "diff";

  const copy = () => {
    navigator.clipboard.writeText(content || src || "");
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="flex flex-col h-full w-full rounded-xl border border-border bg-background overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          <span className="text-sm font-medium text-foreground truncate">{title}</span>
          {hasTabs && (
            <div className="flex items-center gap-0.5">
              <button
                onClick={() => setTab("rendered")}
                className={`px-2.5 py-1.5 text-xs font-medium border-b-2 transition-colors cursor-pointer ${
                  tab === "rendered"
                    ? "border-foreground text-foreground"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                }`}
              >
                Preview
              </button>
              <button
                onClick={() => setTab("raw")}
                className={`px-2.5 py-1.5 text-xs font-medium border-b-2 transition-colors cursor-pointer ${
                  tab === "raw"
                    ? "border-foreground text-foreground"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                }`}
              >
                Code
              </button>
            </div>
          )}
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={copy}
            className="flex size-7 items-center justify-center rounded-lg text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
            aria-label="Copy"
          >
            {copied ? (
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            ) : (
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
            )}
          </button>
          <button
            onClick={onClose}
            className="flex size-7 items-center justify-center rounded-lg text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
            aria-label="Close canvas"
          >
            <svg className="size-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {renderContent(contentType, content, src, tab, isCode)}
      </div>
    </div>
  );
}

function renderContent(
  contentType: string,
  content: string,
  src: string | undefined,
  tab: "rendered" | "raw",
  isCode: boolean,
) {
  // Image
  if (contentType === "image") {
    return src ? (
      <div className="p-4">
        <img src={src} alt="Canvas content" className="max-w-full h-auto rounded-lg" />
      </div>
    ) : (
      <p className="p-4 text-sm text-muted-foreground">No image source</p>
    );
  }

  // PDF
  if (contentType === "pdf") {
    return src ? (
      <iframe src={src} className="w-full h-full min-h-[600px] border-0" title="PDF preview" />
    ) : (
      <p className="p-4 text-sm text-muted-foreground">No PDF source</p>
    );
  }

  // Pure code types — syntax-highlighted, fills the panel
  if (isCode) {
    return <CodeBlockCode code={content} language={contentType} className="[&>pre]:!bg-transparent" />;
  }

  // Markdown
  if (contentType === "markdown") {
    if (tab === "raw") {
      return <CodeBlockCode code={content} language="markdown" className="[&>pre]:!bg-transparent" />;
    }
    return (
      <div className="p-4">
        <TextPart text={content} />
      </div>
    );
  }

  // HTML
  if (contentType === "html") {
    if (tab === "raw") {
      return <CodeBlockCode code={content} language="html" className="[&>pre]:!bg-transparent" />;
    }
    return (
      <iframe
        srcDoc={content}
        className="w-full h-full min-h-[400px] border-0 bg-white"
        sandbox="allow-scripts"
        title="HTML preview"
      />
    );
  }

  // Diff
  if (contentType === "diff") {
    if (tab === "raw") {
      return <pre className="p-4 text-sm font-mono whitespace-pre-wrap break-words text-foreground">{content}</pre>;
    }
    return <DiffView content={content} />;
  }

  // Fallback
  return <pre className="p-4 text-sm font-mono whitespace-pre-wrap break-words text-foreground">{content}</pre>;
}

function DiffView({ content }: { content: string }) {
  const lines = content.split("\n");
  return (
    <div className="font-mono text-sm">
      {lines.map((line, i) => {
        let bg = "";
        let textColor = "text-foreground";
        if (line.startsWith("+")) {
          bg = "bg-green-500/10";
          textColor = "text-green-700 dark:text-green-400";
        } else if (line.startsWith("-")) {
          bg = "bg-red-500/10";
          textColor = "text-red-700 dark:text-red-400";
        } else if (line.startsWith("@@")) {
          bg = "bg-blue-500/10";
          textColor = "text-blue-700 dark:text-blue-400";
        }
        return (
          <div key={i} className={`px-4 py-0.5 ${bg} ${textColor}`}>
            <span className="whitespace-pre-wrap break-all">{line}</span>
          </div>
        );
      })}
    </div>
  );
}
