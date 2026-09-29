import { useEffect, useState } from "react";
import type { DesignVersion } from "../hooks/use-files";
import { track } from "../lib/analytics";
import { getLang, t } from "../lib/i18n";
import { useToast } from "../lib/toast";
import { flushDesignEditor, reloadDesignEditors, type DesignHost } from "./design-editor-view";

// A design's earlier versions (cycls/_agent/versions.py): each is what a save, an
// agent's edit or a restore replaced. Restore brings one back (what's there now is
// kept as a version too, so a restore is undone by restoring); Open as copy makes it
// a new design beside this one.

function ago(iso: string): string {
  const s = (Date.parse(iso) - Date.now()) / 1000;
  const rtf = new Intl.RelativeTimeFormat(getLang(), { numeric: "auto" });
  const abs = Math.abs(s);
  if (abs < 60) return rtf.format(0, "second");
  if (abs < 3600) return rtf.format(Math.round(s / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(s / 3600), "hour");
  return rtf.format(Math.round(s / 86400), "day");
}

// What replaced it, as the row says it.
function whatReplacedIt(v: DesignVersion): string {
  if (v.reason === "agent") return v.intent ? t("versionBeforeAgentIntent").replace("{intent}", v.intent) : t("versionBeforeAgent");
  if (v.reason === "restore") return t("versionBeforeRestore");
  if (v.reason === "keep") return t("versionBeforeKeep");
  return t("versionSaved");
}

export function VersionHistory({ path, host, onClose }: { path: string; host: DesignHost; onClose: () => void }) {
  const [rows, setRows] = useState<DesignVersion[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const toast = useToast();
  const dir = path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "";
  const stem = (path.split("/").pop() ?? path).replace(/\.fig$/i, "");

  useEffect(() => {
    let live = true;
    host.listVersions?.(path).then((r) => { if (live) setRows(r); }).catch(() => { if (live) setRows([]); });
    return () => { live = false; };
  }, [host, path]);

  const restore = async (v: DesignVersion) => {
    if (!host.restoreVersion) return;
    setBusy(v.id);
    try {
      await flushDesignEditor(path, 3000);   // an open editor's unsaved work lands first — and is kept as a version
      await host.restoreVersion(path, v.id);
      reloadDesignEditors(path);
      track("design_version_restored", { reason: v.reason });
      toast.info(t("versionRestored"));
      onClose();
    } catch {
      toast.error(t("versionRestoreFailed"));
    } finally {
      setBusy(null);
    }
  };

  const openCopy = async (v: DesignVersion) => {
    if (!host.versionBlob) return;
    setBusy(v.id);
    try {
      const blob = await host.versionBlob(path, v.id);
      const written = await host.writeNew(`${dir ? `${dir}/` : ""}${stem} ${t("versionCopySuffix")}.fig`, blob);
      host.refreshFiles?.();
      host.openInCanvas(written);
      onClose();
    } catch {
      toast.error(t("copyFailed"));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="absolute inset-0 z-20 flex justify-end bg-black/20" onClick={onClose}>
      <div className="flex h-full w-80 max-w-full flex-col border-s border-border bg-background shadow-xl"
           role="dialog" aria-label={t("versionHistory")} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div className="text-sm font-medium text-foreground">{t("versionHistory")}</div>
          <button onClick={onClose} aria-label={t("close")}
                  className="cursor-pointer rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-secondary">✕</button>
        </div>
        <div className="flex-1 overflow-y-auto p-2">
          {rows === null && <div className="p-3 text-xs text-muted-foreground">{t("loading")}</div>}
          {rows?.length === 0 && <div className="p-3 text-xs text-muted-foreground">{t("versionNone")}</div>}
          {rows?.map((v) => (
            <div key={v.id} className="rounded-lg px-3 py-2 hover:bg-secondary/60" data-testid="design-version">
              <div className="text-xs font-medium text-foreground" dir="auto">{whatReplacedIt(v)}</div>
              <div className="text-[11px] text-muted-foreground">{ago(v.at)} · {v.by === "agent" ? t("versionByAgent") : t("versionByYou")}</div>
              <div className="mt-1.5 flex gap-2">
                <button disabled={!!busy} onClick={() => void restore(v)}
                        className="cursor-pointer rounded-md bg-secondary px-2 py-1 text-[11px] font-medium text-foreground hover:bg-secondary/80 disabled:opacity-50">
                  {t("versionRestore")}
                </button>
                <button disabled={!!busy} onClick={() => void openCopy(v)}
                        className="cursor-pointer rounded-md px-2 py-1 text-[11px] text-muted-foreground hover:bg-secondary disabled:opacity-50">
                  {t("versionOpenCopy")}
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
