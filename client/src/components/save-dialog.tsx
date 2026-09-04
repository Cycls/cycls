import { useEffect, useState } from "react";
import { Icon } from "./icon";
import { LoadingBar } from "./loading-bar";
import { t } from "../lib/i18n";

// An app can propose a file name. Where it lands is this dialog's answer,
// which is why an app needs no permission to write outside its own folder.
export function SaveDialog({ name, bytes, listFolders, onConfirm, onCancel }: {
  name: string;
  bytes: number;
  listFolders: () => Promise<{ name: string; path: string }[]>;
  onConfirm: (path: string) => void;
  onCancel: () => void;
}) {
  const [folders, setFolders] = useState<{ name: string; path: string }[] | null>(null);
  const [dir, setDir] = useState("");
  const [filename, setFilename] = useState(name);
  const [q, setQ] = useState("");

  useEffect(() => { listFolders().then(setFolders); }, [listFolders]);

  const clean = filename.trim().split(/[/\\]/).pop()?.trim() ?? "";
  const dest = dir ? `${dir}/${clean}` : clean;
  const list = [{ name: "", path: "" }, ...(folders || [])]
    .filter((f) => f.path.toLowerCase().includes(q.toLowerCase()));

  return (
    <>
      <div className="fixed inset-0 z-[60] bg-black/30 backdrop-blur-[2px]" onClick={onCancel} />
      <div
        dir="ltr"
        className="fixed left-1/2 top-1/2 z-[60] flex max-h-[70vh] w-[calc(100%-2rem)] max-w-sm -translate-x-1/2 -translate-y-1/2 flex-col rounded-xl border border-border bg-background shadow-xl"
      >
        <div className="border-b border-border px-4 py-3">
          <div className="text-sm font-medium text-foreground">{t("saveToWorkspace")}</div>
          <div className="mt-0.5 truncate text-xs text-muted-foreground">
            {(bytes / 1024).toFixed(bytes < 10_240 ? 1 : 0)} KB
          </div>
        </div>

        <div className="space-y-2 border-b border-border p-2">
          <input
            value={filename}
            onChange={(e) => setFilename(e.target.value)}
            spellCheck={false}
            className="h-8 w-full rounded-md border border-border bg-background px-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-accent"
          />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t("sortName")}
            className="h-8 w-full rounded-md border border-border bg-background px-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-accent"
          />
        </div>

        <div className="flex-1 overflow-y-auto py-1">
          {folders === null ? <LoadingBar /> : list.map((f) => (
            <button
              key={f.path || "/"}
              onClick={() => setDir(f.path)}
              className={`flex w-full cursor-pointer items-center gap-2 px-4 py-2 text-sm hover:bg-secondary/80 ${
                f.path === dir ? "text-foreground" : "text-muted-foreground"
              }`}
            >
              <Icon name="folder" className="size-4 shrink-0" />
              <span className="truncate">{f.path || t("workspace")}</span>
              {f.path === dir && <Icon name="check" className="ms-auto size-3.5 shrink-0" />}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2 border-t border-border px-4 py-3">
          <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-muted-foreground">{dest}</span>
          <button onClick={onCancel} className="cursor-pointer rounded-md px-2.5 py-1.5 text-sm text-muted-foreground hover:bg-secondary">
            {t("cancel")}
          </button>
          <button
            disabled={!clean}
            onClick={() => onConfirm(dest)}
            className="cursor-pointer rounded-md bg-foreground px-2.5 py-1.5 text-sm font-medium text-background disabled:opacity-40"
          >
            {t("save")}
          </button>
        </div>
      </div>
    </>
  );
}
