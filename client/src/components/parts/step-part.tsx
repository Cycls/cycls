import { memo } from "react";
import { cn } from "../../lib/utils";
import { Icon, type IconName } from "../icon";
import { Favicon } from "./sources-part";
import { ext, tintTile, tintLabel } from "../canvas-utils";

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

export const StepPart = memo(function StepPart({
  step,
  toolName,
  isStreaming,
  ok,
}: {
  step: string;
  toolName?: string;
  isStreaming?: boolean;
  ok?: boolean;
}) {
  return (
    <div className="flex items-center gap-2 py-1 text-sm text-muted-foreground">
      <StepDot live={isStreaming} toolName={toolName} step={step} ok={ok} />
      <span className="font-mono text-[13px] truncate">
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
          </>
        ) : (
          step
        )}
      </span>
    </div>
  );
});
