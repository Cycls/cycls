import { memo, useEffect, useState } from "react";
import { cn } from "../../lib/utils";
import { Icon, type IconName } from "../icon";
import { Favicon } from "./sources-part";
import { ext, tintTile, tintLabel } from "../canvas-utils";
import { stepText, t } from "../../lib/i18n";

// A built-in tool wears its own glyph, the way a connector wears its logo. A row with a face keeps no
// check: the shimmer stopping is what says it finished, and a red tint is what says it didn't.
const GLYPHS: Record<string, IconName> = {
  "Web Search": "globe",
  Fetching: "link",
  Reading: "doc",
  Editing: "pencil",
  Bash: "terminal",
  Database: "database",
  Skill: "star",
  "Finding tools": "search",
};

const pageUrl = (s?: string) => {
  const first = s?.trim().split(/\s/)[0] ?? "";
  return /^https?:\/\//.test(first) ? first : null;
};

const fileName = (s?: string) => {
  const first = s?.trim().split(/\s/)[0] ?? "";
  return /\.[a-z0-9]{1,6}$/i.test(first) ? first.split("/").pop()! : null;
};

// Reading or writing a file wears the tinted extension tile the canvas and the file cards give it.
const FileTile = ({ name, live }: { name: string; live?: boolean }) => (
  <span className="relative flex size-5 shrink-0 items-center justify-center overflow-hidden rounded-[6px] bg-secondary" style={tintTile(name)}>
    <span className="text-[7px] font-semibold uppercase leading-none tracking-tighter text-muted-foreground" style={tintLabel(name)}>{ext(name).slice(0, 3)}</span>
    {live && <span className="logo-shimmer absolute inset-y-0 -inset-x-full" />}
  </span>
);

export const StepDot = ({ live, toolName, step, ok }: { live?: boolean; toolName?: string; step?: string; ok?: boolean }) => {
  const file = toolName === "Reading" || toolName === "Editing" ? fileName(step) : null;
  if (file) return <FileTile name={file} live={live} />;
  const page = toolName === "Fetching" ? pageUrl(step) : null;   // a fetched page shows its own favicon
  if (page) {
    return (
      <span className="relative flex size-5 shrink-0 items-center justify-center overflow-hidden rounded">
        <Favicon url={page} className="size-4" />
        {live && <span className="logo-shimmer absolute inset-y-0 -inset-x-full" />}
      </span>
    );
  }
  const glyph = toolName && GLYPHS[toolName];
  if (glyph) {
    return (
      <span className="flex size-5 shrink-0 items-center justify-center">
        <Icon name={glyph} strokeWidth={1} className={cn("size-[18px]", live ? "icon-shimmer" : ok === false ? "text-destructive" : "text-muted-foreground")} />
      </span>
    );
  }
  return (
    <div className={cn("flex size-5 shrink-0 items-center justify-center rounded-full border", live ? "border-accent" : ok === false ? "border-destructive/40 bg-destructive/10" : "border-border bg-accent/10")}>
      {live ? <span className="block size-1.5 rounded-full bg-accent animate-pulse" /> : (
        <svg className={cn("size-3", ok === false ? "text-destructive" : "text-accent")} fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={ok === false ? "M6 18L18 6M6 6l12 12" : "M5 13l4 4L19 7"} />
        </svg>
      )}
    </div>
  );
};

// What a tool call is being given, while the model is still writing it: the text of
// the value it's on (a slide's headline, a file's latest line). A deck's input streams
// for minutes — with only the tool's name on screen that read as stuck.
export function writingNow(args?: string): string {
  if (!args) return "";
  const tail = args.slice(-400);
  const start = tail.lastIndexOf('": "');
  if (start < 0) return "";
  let text = tail.slice(start + 4);
  for (let i = 0; i < text.length; i++) {            // up to the value's closing quote, if it has closed
    if (text[i] === "\\") i++;
    else if (text[i] === '"') { text = text.slice(0, i); break; }
  }
  text = text.replace(/\\u[0-9a-fA-F]{0,3}$|\\$/, "");   // an escape cut off by the stream
  try { text = JSON.parse(`"${text}"`); } catch { text = text.replace(/\\[nrt]/g, " ").replace(/\\(.)/g, "$1"); }
  return text.replace(/\s+/g, " ").trim().slice(-80);
}

// Seconds a live step has been going — shown once it's long enough to wonder about.
function useElapsed(at: number | undefined, live: boolean | undefined): string | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!live || !at) return;
    const h = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(h);
  }, [live, at]);
  if (!live || !at) return null;
  const secs = Math.floor((now - at) / 1000);
  if (secs < 5) return null;
  return secs < 60 ? `${secs}s` : `${Math.floor(secs / 60)}m ${String(secs % 60).padStart(2, "0")}s`;
}

export const StepPart = memo(function StepPart({
  step,
  toolName,
  isStreaming,
  ok,
  args,
  at,
}: {
  step: string;
  toolName?: string;
  isStreaming?: boolean;
  ok?: boolean;
  args?: string;   // the call's input so far (partial JSON) — a live row previews it until its label arrives
  at?: number;     // when the step appeared
}) {
  const elapsed = useElapsed(at, isStreaming);
  const writing = isStreaming && toolName && !step ? writingNow(args) : "";
  return (
    <div className="flex items-center gap-2 py-1 text-sm text-muted-foreground">
      <StepDot live={isStreaming} toolName={toolName} step={step} ok={ok} />
      <span className="font-mono text-[13px] truncate" dir="auto">
        {toolName ? (
          <>
            <span className="font-semibold text-foreground">{toolName}</span>
            {step && (
              <>
                <span className="text-foreground">(</span>
                {step}
                <span className="text-foreground">)</span>
              </>
            )}
            {isStreaming && !step && args && (
              <span data-testid="step-writing"> — {t("writingInput")}{writing && <> “{writing}”</>}</span>
            )}
          </>
        ) : (
          stepText(step)
        )}
      </span>
      {elapsed && <span data-testid="step-elapsed" className="shrink-0 text-xs tabular-nums text-muted-foreground/60">{elapsed}</span>}
    </div>
  );
});
