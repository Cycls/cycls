import { useEffect, useState, type ReactNode } from "react";
import { Popover } from "./popover";
import { Icon } from "./icon";
import { AppTile } from "./app-icon";
import { FileTile } from "./parts/file-part";
import { shownName } from "./canvas-utils";
import { WsIcon } from "./workspace-switcher";
import { fold, matchTokens } from "../hooks/use-files";
import { useEscape } from "../hooks/use-escape";
import { t, getLang } from "../lib/i18n";
import type { AppInfo } from "../hooks/use-apps";
import type { Everywhere } from "../hooks/use-workspaces";

export type Kind = "chats" | "files" | "apps";
type Ws = Everywhere["workspaces"][number];
type Hit = { key: string; title: string; ws?: string; folders?: string[]; meta?: string; icon: ReactNode; open: () => void };

const UNDER_ALL = 5;   // per kind under All; a filter shows every match
const tile = "flex size-8 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-secondary text-muted-foreground";

// Everything by its name: chat titles, files, apps. With workspaces, in every one you may enter (`everywhere`) or the
// one picked, each hit saying where it lives (workspace / folder) and opened there; else the open workspace's, as the
// sidebar lists it.
export function SearchDialog({ chats, apps, searchFiles, everywhere, here, onOpen, onClose }: {
  chats?: { id: string; title: string; updatedAt: string }[];   // absent when signed out
  apps?: AppInfo[];
  searchFiles?: (query: string) => Promise<{ name: string; path: string }[]>;
  everywhere?: (query: string, ws?: string) => Promise<Everywhere>;
  here?: string;   // the workspace you're in
  onOpen: (kind: Kind, key: string, ws?: string) => void;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<Kind | "all">("all");
  const [scope, setScope] = useState<string>();   // the one workspace picked
  const [picking, setPicking] = useState(false);
  const [files, setFiles] = useState<{ name: string; path: string }[]>([]);
  const [all, setAll] = useState<Everywhere | null>(null);
  const [active, setActive] = useState(0);
  useEscape(() => setPicking(false), picking);

  useEffect(() => {
    let live = true;
    const look = everywhere ? () => everywhere(query, scope).then((r) => live && setAll(r))
      : searchFiles && (() => searchFiles(query).then((r) => live && setFiles(r)));
    if (!look) return;
    const wait = setTimeout(() => void look().catch(() => {}), 150);
    return () => { live = false; clearTimeout(wait); };
  }, [query, scope, everywhere, searchFiles]);
  useEffect(() => setActive(0), [query, kind, scope]);

  const tokens = fold(query).split(/\s+/).filter(Boolean);
  const day = (iso: string) => iso ? new Date(iso).toLocaleDateString(getLang(), { month: "short", day: "numeric" }) : "";
  const spaces = all && all.workspaces.length > 1 ? all.workspaces : [];   // a hit says where it lives once there's a choice
  const named = (w: Ws) => (w.id.startsWith("u-") ? t("personal") : w.name);
  const mark = (w: Ws) => <WsIcon ws={w.id.startsWith("u-") ? null : w} />;
  const picked = spaces.find((w) => w.id === scope);
  const kept = <T extends { ws?: string }>(xs: T[]) => (scope ? xs.filter((x) => x.ws === scope) : xs);
  const chatsFound: { id: string; title: string; updatedAt: string; ws?: string }[] =
    all?.chats ?? (chats || []).filter((c) => matchTokens(c.title || "", tokens));
  const filesFound: { name: string; path: string; ws?: string }[] = all?.files ?? files;
  const appsFound: { slug: string; name: string; description?: string; ws?: string }[] =
    all?.apps ?? (apps || []).filter((a) => matchTokens(`${a.name} ${a.description ?? ""}`, tokens));
  const found: Partial<Record<Kind, Hit[]>> = {
    ...((all || chats) && { chats: kept(chatsFound).map((c) => ({
      key: `${c.ws}/${c.id}`, title: c.title || t("untitled"), ws: c.ws, meta: day(c.updatedAt),
      icon: <span className={tile}><Icon name="chat" strokeWidth={1.5} /></span>, open: () => onOpen("chats", c.id, c.ws) })) }),
    ...((all || searchFiles) && { files: kept(filesFound).map((f) => {
      const folders = f.path.split("/").slice(0, -1);
      return { key: `${f.ws}/${f.path}`, title: shownName(f.name), ws: f.ws, folders,
        meta: spaces.length ? undefined : folders.join("/") || t("workspace"),
        icon: <FileTile name={f.name} className="size-8" />, open: () => onOpen("files", f.path, f.ws) };
    }) }),
    ...((all || apps) && { apps: kept(appsFound).map((a) => ({
      key: `${a.ws}/${a.slug}`, title: a.name, ws: a.ws, meta: spaces.length ? undefined : a.description,
      icon: <AppTile app={((!a.ws || a.ws === here) && apps?.find((x) => x.slug === a.slug)) || a} className="size-8" textClassName="text-lg" />,
      open: () => onOpen("apps", a.slug, a.ws) })) }),
  };
  const kinds = (["chats", "files", "apps"] as Kind[]).filter((k) => found[k]);
  const sections = (kind === "all" ? kinds : [kind])
    .map((k) => [k, kind === "all" ? found[k]!.slice(0, UNDER_ALL) : found[k]!] as const)
    .filter(([, hits]) => hits.length);
  const flat = sections.flatMap(([, hits]) => hits);
  const open = (hit?: Hit) => { if (hit) { hit.open(); onClose(); } };

  // Workspace / folder / folder, as the Files panel reads; with one workspace picked, its folders alone.
  const where = (hit: Hit) => {
    const w = !scope && spaces.find((x) => x.id === hit.ws);
    const parts = [...(w ? [named(w)] : []), ...(hit.folders ?? [])];
    return spaces.length > 0 && parts.length > 0 && (
      <span className="mt-0.5 flex min-w-0 items-center gap-1 text-xs text-muted-foreground">
        {w && mark(w)}
        {parts.map((p, i) => (
          <span key={i} className="flex min-w-0 items-center gap-1">
            {i > 0 && <span className="shrink-0 text-muted-foreground/40">/</span>}
            <span dir="auto" className="truncate">{p}</span>
          </span>
        ))}
      </span>
    );
  };

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
        <div className="flex items-center gap-1 border-b border-border px-4 pb-3 pt-3">
          {(["all", ...kinds] as const).map((k) => (
            <button key={k} onClick={() => setKind(k)}
              className={`cursor-pointer rounded-full px-3 py-1 text-sm transition-colors ${kind === k ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground"}`}>
              {t(k)}
            </button>
          ))}
          {spaces.length > 0 && (
            <div className="relative ms-auto">
              <button onClick={() => setPicking((p) => !p)} aria-expanded={picking} aria-label={t("workspaces")}
                className={`flex h-7 cursor-pointer items-center gap-1.5 rounded-full border px-2.5 text-sm transition-colors ${picked ? "border-border text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`}>
                {picked ? mark(picked) : <Icon name="grid" className="size-4 shrink-0 sm:hidden" />}
                <span className="max-w-32 truncate max-sm:hidden">{picked ? named(picked) : t("allWorkspaces")}</span>
                <Icon name="chevron-down" className="size-3 shrink-0" />
              </button>
              {picking && (
                <>
                  <div className="fixed inset-0 z-10" onClick={() => setPicking(false)} />
                  <div className="absolute end-0 top-full z-20 mt-1 max-h-72 w-56 overflow-y-auto rounded-lg border border-border bg-background py-1 shadow-lg">
                    {[undefined, ...spaces].map((w) => (
                      <button key={w?.id ?? ""} onClick={() => { setScope(w?.id); setPicking(false); }}
                        className={`flex w-full cursor-pointer items-center gap-2 px-3 py-1.5 text-sm transition-colors ${w?.id === scope ? "bg-secondary/60 text-foreground" : "text-muted-foreground hover:bg-secondary/80 hover:text-foreground"}`}>
                        {w ? mark(w) : <Icon name="grid" className="size-4 shrink-0" />}
                        <span className="truncate">{w ? named(w) : t("allWorkspaces")}</span>
                        {w?.id === here && <span className="ms-auto shrink-0 text-xs">{t("youAreHere")}</span>}
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}
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
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm text-foreground"><bdi>{hit.title}</bdi></span>
                      {where(hit)}
                    </span>
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
