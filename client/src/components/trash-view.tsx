import { LoadingBar } from "./loading-bar";
import { Icon } from "./icon";
import { t } from "../lib/i18n";
import { tintTile, tintLabel } from "./canvas-utils";
import { FolderIcon } from "./files";

// The workspace trash — files, apps and chats in one list (docs/notes/trash.md).
// Restore is for anyone who can edit; delete-forever and empty are admin-only.
export interface TrashRow {
  id: string;
  path: string;      // original path, or the chat title
  kind: string;      // file | dir | app | chat
  by: string;        // user | agent
  deleted_at: string;
  reason?: string;   // delete | overwrite
}

function ago(iso: string) {
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  return days <= 0 ? t("today") : t("daysAgo").replace("{n}", String(days));
}

function Tile({ row, name }: { row: TrashRow; name: string }) {
  if (row.kind === "dir") return <FolderIcon className="size-5 text-muted-foreground shrink-0" />;
  if (row.kind === "chat") {
    return (
      <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-secondary text-muted-foreground">
        <svg className="size-4" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M8 10h8M8 14h5M21 12c0 4.4-4 8-9 8a9.8 9.8 0 01-4-.8L3 20l1.1-3.3A7.3 7.3 0 013 12c0-4.4 4-8 9-8s9 3.6 9 8z" />
        </svg>
      </span>
    );
  }
  if (row.kind === "app") {
    return <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-accent/15 text-[10px] font-medium uppercase text-accent">app</span>;
  }
  return (
    <div className="bg-secondary flex size-8 shrink-0 items-center justify-center rounded-lg" style={tintTile(name)}>
      <span className="text-[10px] font-medium text-muted-foreground uppercase" style={tintLabel(name)}>{name.split(".").pop()}</span>
    </div>
  );
}

export function TrashView({ rows, loading, canPurge, filter, onBack, onRestore, onPurge, onEmpty }: {
  rows: TrashRow[];
  loading: boolean;
  canPurge: boolean;
  filter?: "chat";
  onBack: () => void;
  onRestore: (row: TrashRow) => void;
  onPurge: (row: TrashRow) => void;
  onEmpty: () => void;
}) {
  const shown = filter ? rows.filter((r) => r.kind === filter) : rows;
  return (
    <div className="flex flex-1 min-h-0 flex-col">
      <div className="flex shrink-0 items-center gap-2 border-b border-border px-4 py-3 sm:px-6">
        <button onClick={onBack} className="flex size-7 items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer" aria-label={t("back")}>
          <Icon name="chevron-left" className="size-4 rtl:rotate-180" />
        </button>
        <span className="text-sm font-medium">{filter === "chat" ? t("recentlyDeleted") : t("trash")}</span>
        <div className="flex-1" />
        {canPurge && shown.length > 0 && !filter && (
          <button
            onClick={() => { if (confirm(t("emptyTrashConfirm"))) onEmpty(); }}
            className="text-xs text-muted-foreground hover:text-red-500 transition-colors cursor-pointer"
          >
            {t("emptyTrash")}
          </button>
        )}
      </div>
      {loading && <LoadingBar active />}
      <div className="flex-1 overflow-y-auto">
        {shown.length === 0 && !loading ? (
          <div className="flex h-full flex-col items-center justify-center gap-1 py-16 text-center">
            <p className="text-sm font-medium">{t("noTrash")}</p>
            <p className="text-xs text-muted-foreground">{t("noTrashSub")}</p>
          </div>
        ) : (
          <ul className="divide-y divide-border/60">
            {shown.map((r) => {
              const name = r.kind === "chat" ? r.path : r.path.split("/").pop() || r.path;
              return (
                <li key={r.id} className="group flex items-center gap-3 px-4 py-2.5">
                  <Tile row={r} name={name} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm">{name}</span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {ago(r.deleted_at)} · {r.by === "agent" ? t("byAgent") : t("byYou")}
                      {r.reason === "overwrite" ? ` · ${t("overwritten")}` : ""}
                      {r.kind !== "chat" && r.path.includes("/") ? ` · ${r.path}` : ""}
                    </span>
                  </span>
                  <button onClick={() => onRestore(r)} className="rounded-lg border border-border px-2.5 py-1 text-xs font-medium hover:bg-secondary transition-colors cursor-pointer">
                    {t("restore")}
                  </button>
                  {canPurge && (
                    <button
                      onClick={() => { if (confirm(t("deleteForeverConfirm").replace("{name}", name))) onPurge(r); }}
                      className="flex size-7 items-center justify-center rounded-md text-muted-foreground/60 hover:text-red-500 hover:bg-secondary/80 transition-colors cursor-pointer"
                      aria-label={t("deleteForever")} title={t("deleteForever")}
                    >
                      <Icon name="x" className="size-3.5" />
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
      <p className="shrink-0 border-t border-border px-4 py-2 text-[11px] text-muted-foreground">{t("noTrashSub")}</p>
    </div>
  );
}
