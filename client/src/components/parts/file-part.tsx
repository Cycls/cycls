import { memo } from "react";
import { tintTile, tintLabel } from "../canvas-utils";

// A deliverable the agent opened in the canvas — rendered as a persistent,
// clickable card (same chip style as user attachments). Click reopens the
// file in the canvas; without a handler (shared views) it's a plain card.
export const FilePart = memo(function FilePart({
  path,
  onOpen,
}: {
  path: string;
  onOpen?: (path: string) => void;
}) {
  const name = path.split("/").pop() || path;
  const ext = name.includes(".") ? name.split(".").pop()! : "file";
  const location = path !== name ? path : `workspace / ${name}`;
  return (
    <button
      type="button"
      onClick={onOpen ? () => onOpen(path) : undefined}
      dir="ltr"
      className={`my-1.5 flex w-fit max-w-full items-center gap-3 rounded-2xl border border-border bg-background p-2 pr-4 text-left transition-colors ${
        onOpen ? "hover:bg-secondary/50 cursor-pointer" : "cursor-default"
      }`}
    >
      <div className="bg-secondary flex size-10 shrink-0 items-center justify-center rounded-lg" style={tintTile(name)}>
        <span className="text-[10px] font-medium uppercase text-muted-foreground" style={tintLabel(name)}>{ext}</span>
      </div>
      <div className="flex min-w-0 flex-col overflow-hidden">
        <span className="truncate text-xs font-medium text-foreground">{name}</span>
        <span className="truncate text-xs text-muted-foreground">{location}</span>
      </div>
    </button>
  );
});
