import { useState } from "react";
import type { DocsTrackedChange } from "../hooks/use-files";
import { t } from "../lib/i18n";
import { cn } from "../lib/utils";

// A Word document's tracked changes, under the editor's header: how many, Accept all / Reject all, and a list to
// take them one by one. The document shows them marked (insertions underlined, deletions struck through, in each
// person's colour); picking one in the list brings it into view.

const quoted = (s: string) => {
  const one = s.replace(/\s+/g, " ").trim();
  return `“${one.length > 60 ? `${one.slice(0, 59)}…` : one}”`;
};

/** What a change did, in a line: "Inserted “…”", "Deleted “…”", "Replaced “…” → “…”". */
export function changeLine(c: DocsTrackedChange): string {
  if (c.other) return t("docsOtherChanges");
  if (c.inserted && c.deleted) return `${t("docsReplaced")} ${quoted(c.deleted)} → ${quoted(c.inserted)}`;
  if (c.inserted) return `${t("docsInserted")} ${quoted(c.inserted)}`;
  return `${t("docsDeleted")} ${quoted(c.deleted ?? "")}`;
}

export function DocsReviewBar({ changes, busy, failed, onTake, onReveal }: {
  changes: DocsTrackedChange[];
  busy: boolean;
  failed: boolean;
  onTake: (action: "accept" | "reject", ids?: string[]) => void;
  onReveal: (change: DocsTrackedChange) => void;
}) {
  const [open, setOpen] = useState(false);
  const count = changes.length;   // one per row of the list, "Formatting and layout changes" included
  return (
    <div className="shrink-0 border-b border-border bg-secondary/40 text-xs" data-testid="docs-review">
      <div className="flex flex-wrap items-center gap-2 px-3 py-1.5">
        <span className="font-medium">{t("docsTrackedChanges")}</span>
        <span className="rounded-full bg-background px-1.5 text-muted-foreground" data-testid="docs-review-count">{count}</span>
        <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open}
                className="cursor-pointer rounded-md px-1.5 py-0.5 text-muted-foreground hover:bg-secondary hover:text-foreground">
          {t("docsReview")} <span aria-hidden="true">{open ? "▴" : "▾"}</span>
        </button>
        {failed && <span className="text-red-600" role="alert">{t("docsChangesFailed")}</span>}
        <div className="flex-1" />
        <button type="button" disabled={busy} onClick={() => onTake("accept")} data-testid="docs-accept-all"
                className="cursor-pointer rounded-md bg-foreground px-2.5 py-1 font-medium text-background hover:opacity-90 disabled:cursor-default disabled:opacity-50">
          {t("docsAcceptAll")}
        </button>
        <button type="button" disabled={busy} onClick={() => onTake("reject")} data-testid="docs-reject-all"
                className="cursor-pointer rounded-md border border-border px-2.5 py-1 font-medium hover:bg-secondary disabled:cursor-default disabled:opacity-50">
          {t("docsRejectAll")}
        </button>
      </div>
      {open && (
        <ul className="max-h-56 overflow-y-auto border-t border-border px-1.5 py-1" data-testid="docs-review-list">
          {changes.map((c) => (
            <li key={c.ids.join(",")} className="flex items-center gap-2 rounded-lg px-1.5 py-1 hover:bg-background">
              <span className="size-2 shrink-0 rounded-full" style={{ background: c.color || "currentColor" }} aria-hidden="true" />
              <button type="button" onClick={() => onReveal(c)} disabled={c.start === undefined}
                      title={[c.author, c.date ? new Date(c.date).toLocaleString() : ""].filter(Boolean).join(" · ")}
                      className={cn("min-w-0 flex-1 truncate text-start", c.start !== undefined && "cursor-pointer hover:underline")} dir="auto">
                {changeLine(c)}
                {c.author && <span className="text-muted-foreground"> · {c.author}</span>}
              </button>
              <button type="button" disabled={busy} onClick={() => onTake("accept", c.ids)} aria-label={t("docsAccept")} title={t("docsAccept")}
                      className="cursor-pointer rounded-md px-1.5 py-0.5 text-green-700 hover:bg-green-600/10 disabled:cursor-default disabled:opacity-50 dark:text-green-400">✓</button>
              <button type="button" disabled={busy} onClick={() => onTake("reject", c.ids)} aria-label={t("docsReject")} title={t("docsReject")}
                      className="cursor-pointer rounded-md px-1.5 py-0.5 text-red-700 hover:bg-red-600/10 disabled:cursor-default disabled:opacity-50 dark:text-red-400">✕</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
