import { useEffect, useState, type ReactNode } from "react";
import { Popover } from "./popover";
import { Icon } from "./icon";
import { AppTile } from "./app-icon";
import { FileTile } from "./parts/file-part";
import { shownName } from "./canvas-utils";
import { fold, matchTokens } from "../hooks/use-files";
import { t, getLang } from "../lib/i18n";
import type { AppInfo } from "../hooks/use-apps";

type Kind = "chats" | "files" | "apps";
type Hit = { key: string; title: string; meta?: string; icon: ReactNode; open: () => void };

const UNDER_ALL = 5;   // per kind under All; a filter shows every match
const tile = "flex size-8 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-secondary text-muted-foreground";

// Everything by its name, as the sidebar lists it: chat titles, the workspace's files, apps.
export function SearchDialog({ chats, apps, searchFiles, onOpenChat, onOpenFile, onOpenApp, onClose }: {
  chats?: { id: string; title: string; updatedAt: string }[];   // absent when signed out
  apps?: AppInfo[];
  searchFiles?: (query: string) => Promise<{ name: string; path: string }[]>;
  onOpenChat: (id: string) => void;
  onOpenFile: (path: string, name: string) => void;
  onOpenApp: (app: AppInfo) => void;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<Kind | "all">("all");
  const [files, setFiles] = useState<{ name: string; path: string }[]>([]);
  const [active, setActive] = useState(0);

  useEffect(() => {
    if (!searchFiles) return;
    let live = true;
    const wait = setTimeout(() => void searchFiles(query).then((r) => live && setFiles(r)), 150);
    return () => { live = false; clearTimeout(wait); };
  }, [query, searchFiles]);
  useEffect(() => setActive(0), [query, kind]);

  const tokens = fold(query).split(/\s+/).filter(Boolean);
  const day = (iso: string) => iso ? new Date(iso).toLocaleDateString(getLang(), { month: "short", day: "numeric" }) : "";
  const found: Partial<Record<Kind, Hit[]>> = {
    ...(chats && { chats: chats.filter((c) => matchTokens(c.title || "", tokens)).map((c) => ({
      key: c.id, title: c.title || t("untitled"), meta: day(c.updatedAt),
      icon: <span className={tile}><Icon name="chat" strokeWidth={1.5} /></span>, open: () => onOpenChat(c.id) })) }),
    ...(searchFiles && { files: files.map((f) => ({
      key: f.path, title: shownName(f.name), meta: f.path.includes("/") ? f.path.slice(0, f.path.lastIndexOf("/")) : t("workspace"),
      icon: <FileTile name={f.name} className="size-8" />, open: () => onOpenFile(f.path, f.name) })) }),
    ...(apps && { apps: apps.filter((a) => matchTokens(`${a.name} ${a.description ?? ""}`, tokens)).map((a) => ({
      key: a.slug, title: a.name, meta: a.description,
      icon: <AppTile app={a} className="size-8" textClassName="text-lg" />, open: () => onOpenApp(a) })) }),
  };
  const kinds = (["chats", "files", "apps"] as Kind[]).filter((k) => found[k]);
  const sections = (kind === "all" ? kinds : [kind])
    .map((k) => [k, kind === "all" ? found[k]!.slice(0, UNDER_ALL) : found[k]!] as const)
    .filter(([, hits]) => hits.length);
  const flat = sections.flatMap(([, hits]) => hits);
  const open = (hit?: Hit) => { if (hit) { hit.open(); onClose(); } };

  return (
    <Popover open onClose={onClose} dim className="left-1/2 top-[12vh] w-[min(40rem,calc(100%-2rem))] -translate-x-1/2">
      <div className="flex h-[min(70vh,34rem)] flex-col overflow-hidden rounded-2xl border border-border bg-background shadow-xl">
        <div className="flex items-center gap-3 px-5 pt-4">
          <Icon name="search" className="size-4 shrink-0 text-muted-foreground" />
          <input autoFocus value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("searchAll")} dir="auto"
            onKeyDown={(e) => {
              if (e.key === "ArrowDown" || e.key === "ArrowUp") {
                e.preventDefault();
                setActive((i) => (i + (e.key === "ArrowDown" ? 1 : -1) + flat.length) % Math.max(flat.length, 1));
              } else if (e.key === "Enter") open(flat[active]);
            }}
            className="min-w-0 flex-1 bg-transparent py-1 text-base outline-none placeholder:text-muted-foreground" />
          <button onClick={onClose} aria-label={t("close")} className="flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground">
            <Icon name="x" className="size-4" />
          </button>
        </div>
        <div className="flex gap-1 border-b border-border px-4 pb-3 pt-3">
          {(["all", ...kinds] as const).map((k) => (
            <button key={k} onClick={() => setKind(k)}
              className={`cursor-pointer rounded-full px-3 py-1 text-sm transition-colors ${kind === k ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground"}`}>
              {t(k)}
            </button>
          ))}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto py-2">
          {flat.length === 0 && <p className="py-12 text-center text-sm text-muted-foreground">{t("noResults")}</p>}
          {sections.map(([k, hits]) => (
            <div key={k} className="pb-1">
              {kind === "all" && <p className="px-5 pb-1 pt-2 text-xs font-medium text-muted-foreground">{t(k)}</p>}
              {hits.map((hit) => {
                const i = flat.indexOf(hit);
                return (
                  <button key={hit.key} onClick={() => open(hit)} onMouseMove={() => setActive(i)}
                    ref={i === active ? (el) => el?.scrollIntoView({ block: "nearest" }) : undefined}
                    className={`flex w-full cursor-pointer items-center gap-3 px-5 py-2 text-start ${i === active ? "bg-secondary" : ""}`}>
                    {hit.icon}
                    <span dir="auto" className="min-w-0 flex-1 truncate text-sm text-foreground [text-align:match-parent]">{hit.title}</span>
                    {hit.meta && <span dir="auto" className="max-w-[40%] shrink-0 truncate text-xs text-muted-foreground">{hit.meta}</span>}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </Popover>
  );
}
