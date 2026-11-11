import { useCallback, useEffect, useRef, useState } from "react";
import { useOrganization } from "@clerk/react";
import type { FileChange } from "../hooks/use-files";
import { useApi } from "../hooks/use-api";
import { ALL, useAllPages } from "../hooks/use-all-pages";
import { fetchAuthed } from "../hooks/use-auth-headers";
import { getLang, t, timeAgo } from "../lib/i18n";
import { saveBlob } from "./canvas-utils";
import { Face } from "./file-details";
import { LoadingBar } from "./loading-bar";

type Event = Omit<FileChange, "action"> & { action?: string; target?: string; ws?: string; ws_name?: string; member?: FileChange["by"]; role?: string;
  audience?: string; format?: string; connector?: string; count?: string; ip?: string; client?: string };

const ACTION: Record<string, Parameters<typeof t>[0]> = {
  created: "didCreate", edited: "didEdit", uploaded: "didUpload", renamed: "auditRenamed", moved: "auditMoved",
  deleted: "auditDeleted", restored: "didRestore", shared: "auditShared", unshared: "auditUnshared",
  workspace_created: "auditWsCreated", workspace_renamed: "auditWsRenamed", workspace_deleted: "auditWsDeleted",
  member_added: "auditMemberAdded", role_changed: "auditRoleChanged", member_removed: "auditMemberRemoved",
  downloaded: "auditDownloaded", deleted_forever: "auditDeletedForever", trash_emptied: "auditTrashEmptied",
  audit_exported: "auditExported", app_published: "auditAppPublished", files_changed: "auditFilesChanged",
  connector_connected: "auditConnected", connector_disconnected: "auditDisconnected", connector_allowed: "auditAllowed",
  connector_blocked: "auditBlocked", connector_permissions: "auditPermissions", connector_action: "auditConnectorAction",
};

// The words for what happened: a public link apart from one for the organization, a download in its format.
const what = (e: Event, member?: string) => {
  const key = e.action === "shared" ? (e.audience === "public" ? "auditSharedPublic" : "auditSharedOrg")
    : e.action === "downloaded" && e.format ? "auditDownloadedAs" : ACTION[e.action ?? ""] ?? "didEdit";
  return t(key).replace("{member}", member || "").replace("{role}", e.role || "").replace("{from}", e.from || "")
    .replace("{format}", (e.format || "").toUpperCase()).replace("{count}", e.count || "").replace("{connector}", e.connector || "");
};

// Where it happened: a file's path and its workspace, a member's workspace, a workspace by its name then.
const place = (e: Event) => e.action?.startsWith("workspace_") ? e.target
  : e.member ? e.ws_name : [e.target, e.ws_name].filter(Boolean).join(" · ");

// The org's audit log: what changed in its team workspaces and in the org, newest first, a page at a time.
export function AuditLog() {
  const { api } = useApi();
  const { memberships } = useOrganization({ memberships: ALL });
  useAllPages(memberships);
  const [rows, setRows] = useState<Event[]>([]);
  const [next, setNext] = useState<string | null | undefined>(undefined);   // undefined: not loaded yet; null: the end
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const end = useRef<HTMLDivElement>(null);

  const more = useCallback(async () => {
    if (loading || next === null) return;
    setLoading(true);
    try {
      const page = await (await api(`/audit${next ? `?after=${encodeURIComponent(next)}` : ""}`)).json();
      setRows((r) => [...r, ...page.events]);
      setNext(page.next);
    } catch { setNext(null); }
    finally { setLoading(false); }
  }, [api, loading, next]);

  useEffect(() => {
    const el = end.current;
    if (!el) return;
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) void more(); });
    io.observe(el);
    return () => io.disconnect();
  }, [more]);

  // A face for anyone in the org, whether or not they have opened the app since the log began.
  const known = Object.fromEntries((memberships?.data ?? []).map((m) => [m.publicUserData?.userId,
    { name: [m.publicUserData?.firstName, m.publicUserData?.lastName].filter(Boolean).join(" ") || m.publicUserData?.identifier,
      image: m.publicUserData?.imageUrl }]));
  const who = (p?: FileChange["by"]) => p && ({ ...known[p.id], ...Object.fromEntries(Object.entries(p).filter(([, v]) => v)) } as FileChange["by"]);

  const exportCsv = async () => {
    setExporting(true);
    try { saveBlob(URL.createObjectURL(await (await fetchAuthed("/audit.csv")).blob()), "audit-log.csv"); }
    finally { setExporting(false); }
  };

  return (
    <div>
      <div className="mb-4 flex items-center gap-3">
        <p className="flex-1 text-sm text-muted-foreground">{t("auditAbout")}</p>
        <button type="button" onClick={exportCsv} disabled={exporting || !rows.length}
                className="shrink-0 cursor-pointer rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-foreground hover:bg-secondary disabled:cursor-default disabled:opacity-50">
          {t("auditExport")}
        </button>
      </div>
      <div className="divide-y divide-border rounded-xl border border-border">
        {rows.map((e, i) => {
          const by = who(e.by)!;
          const member = who(e.member);

          return (
            <div key={i} className="flex gap-3 px-4 py-3">
              <Face c={{ ...e, by } as FileChange} size={28} />
              <div className="min-w-0 flex-1 text-sm">
                <div className="flex items-baseline gap-2">
                  <span className="min-w-0 flex-1 truncate">
                    <span className="font-medium text-foreground">{by.you ? t("you") : by.name || t("someone")}</span>
                    <span className="text-muted-foreground"> · {what(e, member?.name)}</span>
                  </span>
                  <span className="shrink-0 text-xs text-muted-foreground" title={new Date(e.at).toLocaleString(getLang())}>{timeAgo(e.at)}</span>
                </div>
                <p className="truncate text-xs text-muted-foreground">
                  <bdi>{place(e)}</bdi>{[e.client, e.ip].filter(Boolean).map((x) => <span key={x} dir="ltr"> · {x}</span>)}
                </p>
              </div>
            </div>
          );
        })}
        {next === null && !rows.length && <p className="px-4 py-10 text-center text-sm text-muted-foreground">{t("auditEmpty")}</p>}
      </div>
      <div ref={end} className="h-6" />
      <LoadingBar active={loading} />
    </div>
  );
}
