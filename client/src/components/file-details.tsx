import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { FileChange, FileEntry, FileInfo } from "../hooks/use-files";
import { useEscape } from "../hooks/use-escape";
import { getLang, t, timeAgo } from "../lib/i18n";
import { peerColor } from "../lib/people";
import { Star } from "./cycls-star";
import { Icon } from "./icon";
import { FileTile } from "./parts/file-part";
import { shownName, tileExt } from "./canvas-utils";

const nameOf = (c: FileChange) => (c.by.you ? t("you") : c.by.name || t("someone"));
const longDate = (iso: string) => new Date(iso).toLocaleString(getLang(), { dateStyle: "medium", timeStyle: "short" });
// The agent's name in the UI's language: this agent's from its brand (set by the chat), any other's as recorded.
let agentLabel = (id: string) => id.charAt(0).toUpperCase() + id.slice(1);
export function setAgentLabel(fn: (id: string) => string) { agentLabel = fn; }

const via = (c: FileChange) =>
  c.agent ? (c.chat ? t("viaAgentIn").replace("{chat}", c.chat.title || "…") : t("viaAgent")).replace("{agent}", agentLabel(c.agent)) : "";

// The person's small round face; a change an agent made for them wears a star.
export function Face({ c, size = 20 }: { c: FileChange; size?: number }) {
  const round = { width: size, height: size, fontSize: size * 0.45 };
  return (
    <span className="relative inline-flex shrink-0" style={{ width: size, height: size }} title={[nameOf(c), via(c)].filter(Boolean).join(" · ")}>
      {c.by.image ? <img src={c.by.image} alt="" style={round} className="rounded-full object-cover" />
        : <span style={{ ...round, background: peerColor(c.by.id) }}
                className="flex items-center justify-center rounded-full font-semibold text-white">
            {((c.by.name || nameOf(c)).trim()[0] ?? "?").toUpperCase()}
          </span>}
      {c.agent && (
        <span style={{ position: "absolute", bottom: -3, insetInlineEnd: -3, width: size * 0.55, height: size * 0.55 }}
              className="flex items-center justify-center rounded-full bg-background shadow-sm">
          <Star size={size * 0.42} className="text-foreground" />
        </span>
      )}
    </span>
  );
}

// "via Super in “Café plan”", the chat a link back to it.
function Via({ c, onOpenChat }: { c: FileChange; onOpenChat?: (id: string) => void }) {
  if (!c.agent) return null;
  if (!c.chat || !onOpenChat) return <>{via(c)}</>;
  const [before, after] = t("viaAgentIn").replace("{agent}", agentLabel(c.agent)).split("{chat}");
  return (<>{before}<button type="button" onClick={() => onOpenChat(c.chat!.id)}
                         className="cursor-pointer underline decoration-muted-foreground/40 underline-offset-2 hover:text-foreground">
    {c.chat.title || "…"}</button>{after}</>);
}

function Change({ c, label, onOpenChat }: { c: FileChange; label: string; onOpenChat?: (id: string) => void }) {
  return (
    <div className="flex gap-3 py-2">
      <span className="w-24 shrink-0 text-xs text-muted-foreground">{label}</span>
      <div className="flex min-w-0 flex-1 gap-2">
        <Face c={c} size={24} />
        <div className="min-w-0 text-sm">
          <p className="truncate text-foreground">{nameOf(c)}</p>
          {c.agent && <p className="text-xs text-muted-foreground"><Via c={c} onOpenChat={onOpenChat} /></p>}
          <p className="text-xs text-muted-foreground">{longDate(c.at)}</p>
        </div>
      </div>
    </div>
  );
}

// A rename names the old name; a move, the folder it was in.
const fromOf = (c: FileChange) => {
  const parts = (c.from || "").split("/");
  return c.action === "moved" ? parts.slice(0, -1).join("/") || t("workspace") : shownName(parts.pop() || "");
};

const ACTION = { created: "didCreate", edited: "didEdit", uploaded: "didUpload", renamed: "didRename", moved: "didMove", restored: "didRestore",
                 app_data: "didChangeData" } as const;

export function FileDetails({ entry, path, size, onClose, onNavigate, onOpenChat, fileInfo }: {
  entry: FileEntry;
  path: string;
  size: string;
  onClose: () => void;
  onNavigate: (dir: string) => void;
  onOpenChat?: (id: string) => void;
  fileInfo?: (path: string) => Promise<FileInfo>;
}) {
  const ref = useRef<HTMLElement>(null);
  const [info, setInfo] = useState<FileInfo | null>(null);
  useEscape(onClose);
  useEffect(() => {
    const away = (e: Event) => { if (!ref.current?.contains(e.target as Node)) onClose(); };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [onClose]);
  useEffect(() => { fileInfo?.(path).then(setInfo, () => setInfo({ activity: [] })); }, [fileInfo, path]);

  const dir = path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "";
  const created = info?.created ?? entry.created, edited = info?.edited ?? entry.edited;
  const row = (label: string, value: React.ReactNode) => (
    <div className="flex gap-3 py-2"><span className="w-24 shrink-0 text-xs text-muted-foreground">{label}</span>
      <span className="min-w-0 flex-1 text-sm text-foreground">{value}</span></div>
  );
  const open = (id: string) => { onOpenChat?.(id); onClose(); };

  return createPortal(
    <aside ref={ref} dir={getLang() === "ar" ? "rtl" : "ltr"}
           className="fixed inset-y-0 right-0 z-[60] flex w-[24rem] max-w-full flex-col border-s border-border bg-background shadow-xl">
      <div className="flex items-center gap-3 border-b border-border px-4 py-3">
        <FileTile name={entry.name} className="size-8" />
        <span dir="auto" className="min-w-0 flex-1 truncate text-sm font-semibold">{shownName(entry.name)}</span>
        <button type="button" onClick={onClose} aria-label={t("close")}
                className="cursor-pointer rounded-md p-1 text-muted-foreground hover:bg-secondary hover:text-foreground">
          <Icon name="x" className="size-4" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-4 py-3">
        <p className="mb-1 text-xs font-medium text-muted-foreground">{t("fileDetails")}</p>
        <div className="divide-y divide-border/60">
          {row(t("sortType"), <span className="uppercase">{tileExt(entry.name) || "—"}</span>)}
          {row(t("sortSize"), <span dir="ltr">{size}</span>)}
          {row(t("fileLocation"), (
            <button type="button" onClick={() => { onNavigate(dir); onClose(); }}
                    className="flex cursor-pointer items-center gap-1.5 hover:underline">
              <Icon name="folder" className="size-4 text-muted-foreground" strokeWidth={1.5} />
              <span dir="auto" className="truncate">{dir || t("workspace")}</span>
            </button>
          ))}
          {created && <Change c={created} label={t("fileCreated")} onOpenChat={open} />}
          {edited ? <Change c={edited} label={t("fileEdited")} onOpenChat={open} />
                  : entry.modified && row(t("fileEdited"), longDate(entry.modified))}
        </div>
        {!!info?.activity.length && (<>
          <p className="mb-1 mt-6 text-xs font-medium text-muted-foreground">{t("fileActivity")}</p>
          {info.activity.map((c, i) => (
            <div key={i} className="flex gap-2.5 py-2">
              <Face c={c} size={24} />
              <div className="min-w-0 flex-1 text-sm">
                <div className="flex items-baseline gap-2">
                  <span dir="auto" className="min-w-0 flex-1 truncate text-foreground">
                    {t(ACTION[c.action ?? "edited"]).replace("{from}", fromOf(c))}
                  </span>
                  <span className="shrink-0 text-xs text-muted-foreground" title={longDate(c.at)}>{timeAgo(c.at)}</span>
                </div>
                <p className="text-xs text-muted-foreground">{nameOf(c)}{c.agent && <> · <Via c={c} onOpenChat={open} /></>}</p>
              </div>
            </div>
          ))}
        </>)}
      </div>
    </aside>,
    document.body,
  );
}
