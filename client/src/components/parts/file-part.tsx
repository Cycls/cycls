import { createContext, memo, useContext } from "react";
import { tintTile, tintLabel } from "../canvas-utils";
import { Icon } from "../icon";
import { t } from "../../lib/i18n";

// What a file's card does besides open: given by the chat that owns the file, so a shared view has none.
export const FileActions = createContext<{ download: (path: string) => void; share?: (path: string) => void } | null>(null);

const ACTION = "flex size-8 cursor-pointer items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground";

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
  const actions = useContext(FileActions);
  const name = path.split("/").pop() || path;
  const ext = name.includes(".") ? name.split(".").pop()! : "file";
  const location = path !== name ? path : `workspace / ${name}`;
  return (
    <div dir="ltr" className="my-1.5 flex w-fit max-w-full items-center rounded-2xl border border-border bg-background">
      <button
        type="button"
        onClick={onOpen ? () => onOpen(path) : undefined}
        className={`flex min-w-0 items-center gap-3 rounded-2xl p-2 pr-4 text-left transition-colors ${
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
      {actions && (
        <div className="flex shrink-0 items-center gap-0.5 border-l border-border px-1.5">
          <button type="button" onClick={() => actions.download(path)} className={ACTION} aria-label={t("download")} title={t("download")}>
            <svg className="size-4" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24">
              <path d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
            </svg>
          </button>
          {actions.share && (
            <button type="button" onClick={() => actions.share!(path)} className={ACTION} aria-label={t("share")} title={t("share")}>
              <Icon name="link" className="size-4" />
            </button>
          )}
        </div>
      )}
    </div>
  );
});
