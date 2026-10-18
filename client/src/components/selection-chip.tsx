import type { DesignSelection } from "./design-editor-view";
import { Icon } from "./icon";
import { t } from "../lib/i18n";

// A design selection attached to a message: the file and the nodes by name.
export function selectionLabel(sel: DesignSelection): string {
  const file = sel.path.split("/").pop() ?? sel.path;
  const names = sel.nodes.map((n) => n.name);
  // which page, on a design of several; where the playhead was, in a video
  const where = sel.page ? `${file} › ${sel.page}` : typeof sel.time === "number" ? `${file} · ${sel.time.toFixed(1)} s` : file;
  return `${where}: ${names.slice(0, 3).join(", ")}${names.length > 3 ? ` +${names.length - 3}` : ""}`;
}

export function SelectionChip({ selection, onRemove }: { selection: DesignSelection; onRemove?: () => void }) {
  return (
    <span className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-border bg-background px-2.5 py-1 text-xs text-foreground"
          data-testid="selection-chip">
      <svg className="size-3.5 shrink-0 text-muted-foreground" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M4 4l7 17 2.5-7.5L21 11 4 4z" />
      </svg>
      <span className="truncate" dir="auto">{selectionLabel(selection)}</span>
      {onRemove && (
        <button type="button" onClick={onRemove} aria-label={t("removeSelection")}
                className="shrink-0 cursor-pointer rounded-full text-muted-foreground hover:text-foreground">
          <Icon name="x" className="size-3" strokeWidth={2.5} />
        </button>
      )}
    </span>
  );
}
