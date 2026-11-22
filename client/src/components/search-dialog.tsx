import { useEffect, useState, type ReactNode } from "react";
import { Popover } from "./popover";
import { Icon } from "./icon";
import { AppTile } from "./app-icon";
import { FileTile } from "./parts/file-part";
import { shownName } from "./canvas-utils";
import { fold, matchTokens } from "../hooks/use-files";
import { t, getLang } from "../lib/i18n";
import type { AppInfo } from "../hooks/use-apps";
import type { Everywhere } from "../hooks/use-workspaces";

export type Kind = "chats" | "files" | "apps";
type Hit = { key: string; title: string; meta?: string; icon: ReactNode; open: () => void };

const UNDER_ALL = 5;   // per kind under All; a filter shows every match
const tile = "flex size-8 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-secondary text-muted-foreground";

// Everything by its name: chat titles, files, apps. With workspaces, in every one you may enter (`everywhere`), a hit
// from another named by its workspace and opened there; else the open workspace's, as the sidebar lists it.
export function SearchDialog({ chats, apps, searchFiles, everywhere, here, onOpen, onClose }: {
  chats?: { id: string; title: string; updatedAt: string }[];   // absent when signed out
  apps?: AppInfo[];
  searchFiles?: (query: string) => Promise<{ name: string; path: string }[]>;
  everywhere?: (query: string) => Promise<Everywhere>;
  here?: string;   // the workspace you're in
  onOpen: (kind: Kind, key: string, ws?: string) => void;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<Kind | "all">("all");
  const [files, setFiles] = useState<{ name: string; path: string }[]>([]);
  const [all, setAll] = useState<Everywhere | null>(null);
  const [active, setActive] = useState(0);

  useEffect(() => {
    let live = true;
    const look = everywhere ? () => everywhere(query).then((r) => live && setAll(r))
      : searchFiles && (() => searchFiles(query).then((r) => live && setFiles(r)));
    if (!look) return;
    const wait = setTimeout(() => void look().catch(() => {}), 150);
    return () => { live = false; clearTimeout(wait); };
  }, [query, everywhere, searchFiles]);
  useEffect(() => setActive(0), [query, kind]);

  const tokens = fold(query).split(/\s+/).filter(Boolean);
  const day = (iso: string) => iso ? new Date(iso).toLocaleDateString(getLang(), { month: "short", day: "numeric" }) : "";
  const where = (ws?: string) => {   // another workspace's hit says whose it is
    const w = ws !== here && all?.workspaces.find((x) => x.id === ws);
    return w ? [w.icon, w.name].filter(Boolean).join(" ") : undefined;
  };
  const chatsFound: { id: string; title: string; updatedAt: string; ws?: string }[] =
    all?.chats ?? (chats || []).filter((c) => matchTokens(c.title || "", tokens));
  const filesFound: { name: string; path: string; ws?: string }[] = all?.files ?? files;
  const appsFound: { slug: string; name: string; description?: string; ws?: string }[] =
    all?.apps ?? (apps || []).filter((a) => matchTokens(`${a.name} ${a.description ?? ""}`, tokens));
  const found: Partial<Record<Kind, Hit[]>> = {
    ...((all || chats) && { chats: chatsFound.map((c) => ({
      key: `${c.ws}/${c.id}`, title: c.title || t("untitled"), meta: where(c.ws) ?? day(c.updatedAt),
      icon: <span className={tile}><Icon name="chat" strokeWidth={1.5} /></span>, open: () => onOpen("chats", c.id, c.ws) })) }),
    ...((all || searchFiles) && { files: filesFound.map((f) => ({
      key: `${f.ws}/${f.path}`, title: shownName(f.name),
      meta: where(f.ws) ?? (f.path.includes("/") ? f.path.slice(0, f.path.lastIndexOf("/")) : t("workspace")),
      icon: <FileTile name={f.name} className="size-8" />, open: () => onOpen("files", f.path, f.ws) })) }),
    ...((all || apps) && { apps: appsFound.map((a) => ({
      key: `${a.ws}/${a.slug}`, title: a.name, meta: where(a.ws) ?? a.description,
      icon: <AppTile app={(!where(a.ws) && apps?.find((x) => x.slug === a.slug)) || a} className="size-8" textClassName="text-lg" />,
      open: () => onOpen("apps", a.slug, a.ws) })) }),
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
