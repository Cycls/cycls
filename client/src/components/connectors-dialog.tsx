// The connector directory and a connector's page (docs/notes/plugins-connectors.md, UI).
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Icon } from "./icon";
import type { ChatApi } from "../hooks/use-chat";
import { t, useLang, getLang } from "../lib/i18n";
import { cn } from "../lib/utils";
import { track } from "../lib/analytics";

// A field the CMS owns is bilingual; one declared in code is the same string in both languages.
export type L = { en: string; ar: string } | null;
export type Connector = {
  name: string; scope: "user" | "workspace" | "either"; kind: "oauth" | "key"; hint: string | null;
  connected: boolean; connected_as: "user" | "workspace" | null;
  admin: boolean; allowed: boolean; on: boolean; org_admin: boolean; team: string | null;
  title: L; description: L; category: L; story: L; about: string | null; icon: string | null;
  prompts: L[]; showcase: "prompts" | "gallery"; gallery: { image: string; caption?: L }[]; gradient: string[] | null;
  links: { label: string; url: string }[];
  use_cases: [string, string][]; skills: [string, string][];
  developer: string | null; website: string | null;
  privacy: string | null; terms: string | null; docs: string | null;
};
type Mode = "allow" | "ask" | "never";
type ToolRow = { name: string; title: string; description: string | null; writes: boolean; mode: Mode };
type PromptRow = { name: string; title: string; description: string | null };
const MODES: Mode[] = ["allow", "ask", "never"];
const MODE_HINT = { allow: "hintAllow", ask: "hintAsk", never: "hintNever" } as const;

// Read a bilingual field in the reader's language, falling back to whatever was written.
export const L = (v: L | undefined): string => (v ? (getLang() === "ar" ? v.ar || v.en : v.en || v.ar) : "");

export const connectorLabel = (c: { name: string; title?: L }) =>
  L(c.title) || c.name.charAt(0).toUpperCase() + c.name.slice(1);

// A logo sits on its own plate, light in either theme (see --color-plate) so a dark mark still reads.
export const PLATE = "overflow-hidden rounded-xl border border-border/60 bg-plate";

// The declared logo, else the site's favicon, else a link glyph — a connector always has a face.
export function ConnectorIcon({ c, className = "size-9" }: { c: Connector; className?: string }) {
  const host = c.website?.replace(/^https?:\/\//, "").split("/")[0];
  const src = c.icon || (host ? `https://www.google.com/s2/favicons?sz=128&domain=${host}` : null);
  return src
    ? <span className={cn(className, "flex shrink-0 items-center justify-center", PLATE)}><img src={src} alt="" className="size-[68%] object-contain" /></span>
    : <span className={cn(className, "flex shrink-0 items-center justify-center rounded-xl bg-secondary text-muted-foreground")}><Icon name="link" className="size-1/2" /></span>;
}

// cycls.com's ember, each stop mixed into the theme background so it reads in light and dark alike.
// Three stops from the CMS, else cycls.com's ember. Each is mixed into the theme background, so it
// reads in light and dark alike.
const panel = (stops: string[] | null) => {
  const [a, b, d] = stops?.length === 3 ? stops : ["#ffbe6e", "#ff8c37", "#962d14"];
  return `radial-gradient(140% 120% at 96% 100%, color-mix(in oklab, ${a} 42%, var(--color-background)) 0%,` +
    ` color-mix(in oklab, ${b} 36%, var(--color-background)) 20%, color-mix(in oklab, ${d} 28%, var(--color-background)) 42%,` +
    ` color-mix(in oklab, ${d} 18%, var(--color-background)) 66%, var(--color-background) 100%)`;
};


const RAIL = ["connectors", "plugins", "skills"] as const;
const H4 = "mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground";
const CARD = "rounded-xl border border-border bg-background/40 px-4";
const CHIP = "rounded-full border border-border bg-secondary/50 px-2.5 py-1 text-xs text-foreground";

// The OAuth window has to keep its opener: the callback posts `cycls:connected` back through it. The
// listener checks the origin, and `closed` is the fallback for a flow finished somewhere else.
export function openAuth(url: string, done: () => void) {
  const win = window.open(url, "cycls:connect", "popup=yes,width=520,height=700");
  if (!win) { window.location.href = url; return; }
  const timer = setInterval(() => {
    if (win.closed) { clearInterval(timer); done(); }
  }, 800);
  setTimeout(() => clearInterval(timer), 5 * 60 * 1000);
}

export function ConnectorsDialog({ api, items, reload, initial, onClose, onUsePrompt }: {
  api: ChatApi["api"];
  items: Connector[] | null;
  reload: () => void;
  initial?: string;
  onClose: () => void;
  onUsePrompt: (text: string, c: Connector) => void;
}) {
  const isAr = useLang() === "ar";
  const [cat, setCat] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<string | null>(initial ?? null);

  const connect = async (c: Connector, scope: "user" | "workspace") => {
    track("connector_connect_clicked", { connector: c.name, source: "directory", scope });
    const { url } = await (await api(`/connectors/${c.name}/authorize?scope=${scope}`, { method: "POST" })).json();
    openAuth(url, reload);
  };
  const disconnect = async (c: Connector) => {
    await api(`/connectors/${c.name}?scope=${c.connected_as ?? "user"}`, { method: "DELETE" });
    track("connector_disconnected", { connector: c.name, scope: c.connected_as });
    reload();
  };
  const allow = async (c: Connector, on: boolean) => {
    await api(`/connectors/${c.name}`, { method: "PATCH", json: { allowed: on } });
    track("connector_toggled", { connector: c.name, to: on ? "on" : "off", level: "org" });
    reload();
  };
  const use = async (c: Connector, on: boolean) => {
    await api(`/connectors/${c.name}`, { method: "PATCH", json: { on } });
    track("connector_toggled", { connector: c.name, to: on ? "on" : "off", level: "user" });
    reload();
  };
  const saveKey = async (c: Connector, key: string, scope: "user" | "workspace") => {
    await api(`/connectors/${c.name}/key`, { method: "PUT", json: { key, scope } });
    track("connector_connect_clicked", { connector: c.name, source: "directory", scope, kind: "key" });
    reload();
  };
  const usePrompt = (c: Connector, text: string) => {
    track("connector_prompt_used", { connector: c.name });
    onUsePrompt(text, c);
    onClose();
  };

  // One list, not two tabs: what you have connected sits at the top with its state, everything else
  // follows. Search and the category chips narrow both halves at once.
  const q = query.trim().toLowerCase();
  const matches = (items ?? []).filter((c) =>
    (!q || connectorLabel(c).toLowerCase().includes(q) || L(c.description).toLowerCase().includes(q))
    && (!cat || L(c.category) === cat));
  const mine = matches.filter((c) => c.connected);
  const rest = matches.filter((c) => !c.connected);
  const list = [...mine, ...rest];
  const cats = [...new Set((items ?? []).map((c) => L(c.category)).filter(Boolean))].sort();
  const detail = open ? items?.find((c) => c.name === open) : null;

  const filters = cats.length > 1 && (
    <div className="-mx-1 mb-4 flex gap-1.5 overflow-x-auto px-1 pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
      {[null, ...cats].map((k) => (
        <button key={k ?? "all"} onClick={() => setCat(k)}
          className={cn("shrink-0 cursor-pointer rounded-full border px-3 py-1 text-xs transition-colors",
            cat === k ? "border-foreground bg-foreground text-background" : "border-border text-muted-foreground hover:text-foreground")}>
          {k ?? t("allConnectors")}
        </button>
      ))}
    </div>
  );
  const search = (
    <div className="relative min-w-0 flex-1">
      <Icon name="search" className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
      <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("searchConnectors")} dir="auto"
        className="w-full rounded-xl border border-border bg-background py-2 pe-3 ps-9 text-sm outline-none placeholder:text-muted-foreground focus:border-foreground/30" />
    </div>
  );

  const cards = (rows: Connector[]) => (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {rows.map((c) => (
        <button key={c.name} onClick={() => setOpen(c.name)} className={cn("flex cursor-pointer flex-col gap-3 rounded-2xl border border-border bg-background/40 p-4 text-start transition hover:border-foreground/25 hover:shadow-sm", !c.allowed && "opacity-50")}>
          <div className="flex items-center gap-3">
            <ConnectorIcon c={c} className="size-10" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-foreground">{connectorLabel(c)}</p>
              {L(c.category) && <p className="truncate text-[11px] text-muted-foreground">{L(c.category)}</p>}
            </div>
            {/* One 28px slot whatever the state, so the column lines up down the grid. */}
            {!c.allowed
              ? <span title={t("offInOrg")} className="flex size-7 shrink-0 items-center justify-center rounded-full border border-border text-muted-foreground"><Icon name="x" className="size-3.5" /></span>
              : c.connected
                ? <span title={c.on ? t("connectedLabel") : t("useInChatsSub")}
                    className={cn("flex size-7 shrink-0 items-center justify-center rounded-full", c.on ? "bg-green-500/15 text-green-600" : "bg-secondary text-muted-foreground")}>
                    {c.on ? <Icon name="check" className="size-3.5" strokeWidth={2.5} /> : <span className="size-1.5 rounded-full bg-current" />}
                  </span>
                : <span title={t("connect")} className="flex size-7 shrink-0 items-center justify-center rounded-full border border-border text-muted-foreground"><Icon name="plus" className="size-3.5" /></span>}
          </div>
          {L(c.description) && <p className="line-clamp-2 text-xs leading-relaxed text-muted-foreground"><bdi>{L(c.description)}</bdi></p>}
        </button>
      ))}
    </div>
  );

  const grid = items === null ? null : list.length === 0 ? (
    <div className="flex flex-col items-center py-20 text-center text-muted-foreground">
      <Icon name="link" className="mb-3 size-8 opacity-30" strokeWidth={1.5} />
      <p className="text-sm">{q || cat ? t("noConnectorsFound") : t("noConnectors")}</p>
    </div>
  ) : (
    <>
      {mine.length > 0 && (
        <section className="mb-6">
          <h4 className={H4}>{t("yours")}</h4>
          {cards(mine)}
        </section>
      )}
      {rest.length > 0 && (
        <section>
          {mine.length > 0 && <h4 className={H4}>{t("discover")}</h4>}
          {cards(rest)}
        </section>
      )}
    </>
  );

  return createPortal(
    <div dir={isAr ? "rtl" : "ltr"}>
      <div className="fixed inset-0 z-[80] bg-black/40 backdrop-blur-[2px]" onClick={onClose} />
      <div className="fixed inset-0 z-[80] flex flex-col overflow-hidden bg-card sm:inset-auto sm:left-1/2 sm:top-1/2 sm:h-[min(720px,90vh)] sm:w-[min(960px,94vw)] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-2xl sm:border sm:border-border sm:shadow-2xl">
        <div className="flex items-center justify-between border-b border-border px-5 py-4 sm:hidden">
          <h2 className="text-lg font-semibold text-foreground">{t("connectors")}</h2>
          <button onClick={onClose} className="cursor-pointer text-muted-foreground hover:text-foreground" aria-label="Close"><Icon name="x" className="size-5" /></button>
        </div>

        <div className="flex min-h-0 flex-1">
          <aside className="hidden w-52 shrink-0 flex-col gap-1 border-e border-border p-3 sm:flex">
            <button onClick={onClose} className="mb-3 flex size-8 cursor-pointer items-center justify-center rounded-lg text-muted-foreground hover:bg-secondary/80 hover:text-foreground" aria-label="Close">
              <Icon name="x" className="size-4" />
            </button>
            {RAIL.map((k) => (
              <div key={k} className={cn("flex items-center justify-between rounded-lg px-3 py-2 text-sm", k === "connectors" ? "bg-secondary font-medium text-foreground" : "text-muted-foreground/60")}>
                {t(k)}
                {k !== "connectors" && <span className="rounded-full border border-border px-1.5 py-px text-[10px]">{t("soon")}</span>}
              </div>
            ))}
          </aside>

          <div className="min-w-0 flex-1 overflow-y-auto px-5 py-5 sm:px-8 sm:py-6">
            {detail ? (
              <Detail c={detail} api={api} onBack={() => setOpen(null)} onConnect={connect} onSaveKey={saveKey} onDisconnect={disconnect} onAllow={allow} onUse={use} onPrompt={usePrompt} />
            ) : (
              <>
                <div className="mb-5 hidden sm:block">
                  <h2 className="text-lg font-semibold text-foreground">{t("connectors")}</h2>
                  <p className="text-sm text-muted-foreground">{t("connectorsSub")}</p>
                </div>
                <div className="mb-4">{search}</div>
                {filters}
                {grid}
              </>
            )}
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}

function Split({ primary, secondary, onPrimary, onSecondary }: { primary: string; secondary: string; onPrimary: () => void; onSecondary: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative shrink-0">
      <div className="flex overflow-hidden rounded-full bg-foreground text-background">
        <button onClick={onPrimary} className="cursor-pointer px-4 py-2 text-sm font-medium transition hover:opacity-80">{primary}</button>
        <button onClick={() => setOpen(!open)} aria-label="More" className="cursor-pointer border-s border-background/30 px-2.5 transition hover:opacity-80"><Icon name="chevron-down" className="size-3.5" /></button>
      </div>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <button onClick={() => { setOpen(false); onSecondary(); }} className="absolute end-0 top-full z-20 mt-2 cursor-pointer whitespace-nowrap rounded-xl border border-border bg-background px-4 py-2.5 text-sm text-foreground shadow-lg hover:bg-secondary/60">{secondary}</button>
        </>
      )}
    </div>
  );
}

// Sized to sit beside a connector's icon, and green when on — the switch is the state, so nothing
// needs a dot next to it.
export function Switch({ on, onChange }: { on: boolean; onChange: (on: boolean) => void }) {
  return (
    <button role="switch" aria-checked={on} onClick={() => onChange(!on)} className={cn("relative h-4 w-7 shrink-0 cursor-pointer rounded-full transition-colors", on ? "bg-green-500" : "bg-muted-foreground/30")}>
      <span className={cn("absolute top-0.5 size-3 rounded-full bg-white shadow-sm transition-all", on ? "start-3.5" : "start-0.5")} />
    </button>
  );
}

// One shape for the key row: same height, same radius, same type size, whichever control it is.
const FIELD = "h-9 rounded-full border border-border bg-background px-4 text-sm text-foreground outline-none placeholder:text-muted-foreground focus:border-foreground/30";

const Out = ({ href }: { href: string }) => (
  <a href={href} target="_blank" rel="noreferrer" className="flex size-6 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground" aria-label="Open link">
    <Icon name="arrow-up-right" className="size-4" />
  </a>
);

function KeyForm({ c, team, onSave }: { c: Connector; team: string | null; onSave: (key: string, scope: "user" | "workspace") => void }) {
  const [key, setKey] = useState("");
  const [scope, setScope] = useState<"user" | "workspace">(c.scope === "workspace" ? "workspace" : "user");
  const choice = c.scope === "either" && !!team && c.admin;
  return (
    // On a phone the three sit on their own line each, full width; from sm they share the header row.
    // One height class on all three, so the field and the scope never disagree about their size.
    <form onSubmit={(e) => { e.preventDefault(); if (key.trim()) onSave(key.trim(), scope); }}
      className="flex w-full shrink-0 flex-col gap-2 sm:w-auto sm:flex-row sm:items-center">
      <input type="password" value={key} onChange={(e) => setKey(e.target.value)} placeholder={c.hint ?? t("apiKey")} autoComplete="off" dir="ltr"
        className={cn(FIELD, "w-full sm:w-44")} />
      {choice && (
        <select value={scope} onChange={(e) => setScope(e.target.value as "user" | "workspace")}
          className={cn(FIELD, "w-full cursor-pointer sm:w-auto")}>
          <option value="user">{t("forMe")}</option>
          <option value="workspace">{t("forTeam").replace("{name}", team ?? "")}</option>
        </select>
      )}
      <button type="submit" disabled={!key.trim()}
        className={cn(FIELD, "w-full shrink-0 cursor-pointer border-foreground bg-foreground text-center font-medium text-background transition hover:opacity-80 disabled:cursor-default disabled:opacity-40 sm:w-auto sm:px-5")}>{t("save")}</button>
    </form>
  );
}

// A store-style carousel: one image per page, snapped, swiped on a phone and dragged or arrowed on a
// desktop. Dots say how many there are and which one you are on.
function Gallery({ items, className }: { items: { image: string; caption?: L }[]; className?: string }) {
  const strip = useRef<HTMLDivElement>(null);
  const [at, setAt] = useState(0);
  const go = (i: number) => {
    const el = strip.current;
    if (el) el.scrollTo({ left: i * el.clientWidth, behavior: "smooth" });
  };
  return (
    <div className={className}>
      <div
        ref={strip}
        dir="ltr"
        onScroll={(e) => setAt(Math.round(e.currentTarget.scrollLeft / Math.max(1, e.currentTarget.clientWidth)))}
        className="flex snap-x snap-mandatory overflow-x-auto rounded-2xl border border-border [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      >
        {items.map((g, i) => (
          <figure key={g.image + i} className="w-full shrink-0 snap-center">
            <img src={g.image} alt={L(g.caption)} loading="lazy" className="aspect-[16/10] w-full bg-secondary object-cover" />
            {L(g.caption) && <figcaption dir="auto" className="px-3 py-2 text-xs text-muted-foreground"><bdi>{L(g.caption)}</bdi></figcaption>}
          </figure>
        ))}
      </div>
      {items.length > 1 && (
        <div className="mt-2 flex justify-center gap-1.5">
          {items.map((g, i) => (
            <button key={g.image + i} onClick={() => go(i)} aria-label={`${i + 1}`}
              className={cn("h-1.5 cursor-pointer rounded-full transition-all", i === at ? "w-4 bg-foreground" : "w-1.5 bg-muted-foreground/40")} />
          ))}
        </div>
      )}
    </div>
  );
}

function Detail({ c, api, onBack, onConnect, onSaveKey, onDisconnect, onAllow, onUse, onPrompt }: {
  c: Connector;
  api: ChatApi["api"];
  onBack: () => void;
  onConnect: (c: Connector, scope: "user" | "workspace") => void;
  onSaveKey: (c: Connector, key: string, scope: "user" | "workspace") => void;
  onDisconnect: (c: Connector) => void;
  onAllow: (c: Connector, on: boolean) => void;
  onUse: (c: Connector, on: boolean) => void;
  onPrompt: (c: Connector, text: string) => void;
}) {
  const label = connectorLabel(c);
  const [rows, setRows] = useState<ToolRow[] | null>(null);
  const [templates, setTemplates] = useState<PromptRow[]>([]);
  useEffect(() => {
    api(`/connectors/${c.name}/tools`, { silent: true }).then((r) => r.json()).then(setRows).catch(() => setRows([]));
    api(`/connectors/${c.name}/prompts`, { silent: true }).then((r) => r.json()).then(setTemplates).catch(() => setTemplates([]));
  }, [c.name]);   // eslint-disable-line react-hooks/exhaustive-deps

  const team = c.team;                         // in a team workspace, its name — where a shared grant lands
  const shared = c.connected_as === "workspace";
  const primary = "shrink-0 cursor-pointer rounded-full px-4 py-2 text-sm font-medium transition hover:opacity-80";
  const solid = cn(primary, "bg-foreground text-background");
  const mine = <button onClick={() => onConnect(c, "user")} className={solid}>{t("connect")}</button>;
  // One button that names where the grant lands; a team grant is an admin's to make and to remove.
  const action = !c.allowed ? null
    : c.connected ? (shared && !c.admin ? null : <button onClick={() => onDisconnect(c)} className={cn(primary, "border border-border text-foreground")}>{t("disconnect")}</button>)
    : c.kind === "key" ? (c.scope === "workspace" && !(team && c.admin) ? null : <KeyForm c={c} team={team} onSave={(k, s) => onSaveKey(c, k, s)} />)
    : c.scope === "user" ? mine
    : !team ? (c.scope === "workspace" ? null : mine)
    : c.scope === "workspace" ? (c.admin && <button onClick={() => onConnect(c, "workspace")} className={solid}>{t("connectFor").replace("{name}", team)}</button>)
    : c.admin ? <Split primary={t("connectFor").replace("{name}", team)} secondary={t("connectJustMe")} onPrimary={() => onConnect(c, "workspace")} onSecondary={() => onConnect(c, "user")} />
    : mine;
  const grey = "bg-muted-foreground/40";
  const status = !c.allowed ? [grey, t("offInOrg")]
    : c.connected ? ["bg-green-500", shared ? t("connectedFor").replace("{name}", team ?? t("workspace")) : c.scope === "user" ? t("connectedLabel") : t("connectedJustMe")]
    : c.scope === "workspace" && !team ? [grey, t("teamOnly")]
    : c.scope !== "user" && team && !c.admin ? [grey, t("adminCanShare")]
    : null;

  const caps = rows?.length ? [rows.some((r) => !r.writes) && t("read"), rows.some((r) => r.writes) && t("write")].filter(Boolean).join(", ") : null;
  const facts = [[t("capabilities"), caps], [t("developer"), c.developer], [t("category"), L(c.category)]].filter(([, v]) => v) as [string, string][];
  const links: [string, string][] = c.links.length
    ? c.links.map((l) => [l.label, l.url] as [string, string])
    : ([[t("website"), c.website], [t("privacyPolicy"), c.privacy], [t("termsLabel"), c.terms], [t("documentation"), c.docs]]
        .filter(([, v]) => v) as [string, string][]);

  // What the page opens with: the store-style carousel when the CMS says so and has images, else the
  // prompts on their gradient. No heading over either — it is the first thing on the page.
  const prompts = c.prompts.map(L).filter(Boolean);
  const showcase = c.showcase === "gallery" && c.gallery.length > 0 ? (
    <Gallery items={c.gallery} className="mt-5" />
  ) : prompts.length > 0 ? (
    <div className="mt-5 flex flex-col gap-2.5 rounded-3xl p-3 sm:p-4" style={{ backgroundImage: panel(c.gradient) }}>
      {prompts.map((p) => (
        <button key={p} onClick={() => onPrompt(c, p)} className="flex w-full cursor-pointer items-center gap-4 rounded-2xl border border-border/50 bg-background/80 px-4 py-3 text-start transition hover:bg-background">
          <span className="min-w-0 flex-1 text-[15px] leading-snug text-foreground"><b className="font-semibold">@{label}</b> <bdi>{p}</bdi></span>
          <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-secondary text-foreground"><Icon name="arrow-right" className="size-4 rtl:rotate-180" /></span>
        </button>
      ))}
    </div>
  ) : null;

  return (
    <div>
      <button onClick={onBack} className="mb-5 flex cursor-pointer items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
        <Icon name="chevron-left" className="size-3.5 rtl:rotate-180" />{t("back")}
      </button>

      {/* Name and action share the row; the line about the connector spans the width beneath it. Kept in
          the column it was wrapping into three words a line on a phone, beside the button. */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-4">
        <div className="flex min-w-0 flex-1 items-center gap-4">
          <ConnectorIcon c={c} className="size-14 sm:size-16" />
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-xl font-semibold leading-tight text-foreground">{label}</h3>
            {L(c.category) && <p className="truncate text-xs text-muted-foreground">{L(c.category)}</p>}
          </div>
        </div>
        {action}
      </div>
      {L(c.description) && <p className="mt-3 text-sm text-muted-foreground"><bdi>{L(c.description)}</bdi></p>}
      {status && <p className="mt-3 flex items-center gap-2 text-xs text-muted-foreground"><span className={cn("size-2 rounded-full", status[0])} />{status[1]}</p>}

      {/* The person's own switch: the grant stays, the tools stop riding along. Mirrors the one in the + menu. */}
      {c.connected && c.allowed && (
        <div className="mt-5 flex items-center justify-between gap-4 rounded-xl border border-border bg-background/40 px-4 py-3">
          <div className="min-w-0">
            <p className="text-sm text-foreground">{t("useInChats")}</p>
            <p className="text-xs text-muted-foreground">{t("useInChatsSub")}</p>
          </div>
          <Switch on={c.on} onChange={(on) => onUse(c, on)} />
        </div>
      )}

      {c.org_admin && (
        <div className="mt-5 flex items-center justify-between gap-4 rounded-xl border border-border bg-background/40 px-4 py-3">
          <div className="min-w-0">
            <p className="text-sm text-foreground">{t("allowedInOrg")}</p>
            <p className="text-xs text-muted-foreground">{t("allowedInOrgSub")}</p>
          </div>
          <Switch on={c.allowed} onChange={(on) => onAllow(c, on)} />
        </div>
      )}

      {showcase}

      {L(c.story)
        ? <div dir={getLang() === "ar" ? "rtl" : "ltr"} className="story mt-6 text-sm leading-relaxed text-foreground/90" dangerouslySetInnerHTML={{ __html: L(c.story) }} />
        : c.about && <p className="mt-6 text-sm leading-relaxed text-foreground/90"><bdi>{c.about}</bdi></p>}

      {c.use_cases.length > 0 && (
        <section className="mt-7">
          <h4 className={H4}>{t("useCases")}</h4>
          <ul className="space-y-1.5">
            {c.use_cases.map(([title, text]) => (
              <li key={title} className="text-sm"><span className="font-medium text-foreground"><bdi>{title}</bdi></span><span className="text-muted-foreground"> — <bdi>{text}</bdi></span></li>
            ))}
          </ul>
        </section>
      )}

      {c.skills.length > 0 && (
        <section className="mt-7">
          <h4 className={H4}>{t("skills")}</h4>
          <div className="flex flex-wrap gap-2">
            {c.skills.map(([name, desc]) => (
              <span key={name} className={CHIP} title={desc || undefined}><bdi>{name}</bdi></span>
            ))}
          </div>
        </section>
      )}

      {/* Connected: the Allow / Ask / Never controls. Otherwise the tools are just chips — a glance
          at what the connector can do, not a wall of descriptions. */}
      {rows && rows.length > 0 && (c.connected && c.allowed
        ? <Permissions c={c} api={api} rows={rows} setRows={setRows} />
        : <ToolChips rows={rows} />)}

      {templates.length > 0 && (
        <section className="mt-7">
          <h4 className={H4}>{t("promptTemplates")}</h4>
          <div className="flex flex-wrap gap-2">
            {templates.map((p) => <span key={p.name} className={CHIP} title={p.description || undefined}>{p.title}</span>)}
          </div>
        </section>
      )}

      {(facts.length > 0 || links.length > 0) && (
        <section className="mt-7">
          <h4 className={H4}>{t("information")}</h4>
          <div className={CARD}>
            {facts.map(([k, v]) => (
              <div key={k} className="flex items-center justify-between gap-4 border-b border-border/60 py-2.5 text-sm last:border-0">
                <span className="text-muted-foreground">{k}</span><span className="text-foreground">{v}</span>
              </div>
            ))}
            {links.map(([k, v]) => (
              <div key={k} className="flex items-center justify-between gap-4 border-b border-border/60 py-2 text-sm last:border-0">
                <span className="text-muted-foreground">{k}</span><Out href={v} />
              </div>
            ))}
          </div>
        </section>
      )}

      <p className="mt-7 text-xs leading-relaxed text-muted-foreground">{t("connectorDisclosure").replace("{name}", label)}</p>
    </div>
  );
}

// Pre-connect: every action the server lists, as chips — read-only and write apart, names only.
function ToolChips({ rows }: { rows: ToolRow[] }) {
  const group = (title: string, list: ToolRow[]) => list.length > 0 && (
    <div className="mb-3 last:mb-0">
      <p className="mb-1.5 text-xs text-muted-foreground">{title}</p>
      <div className="flex flex-wrap gap-2">
        {list.map((r) => <span key={r.name} className={CHIP} title={r.description || undefined}>{r.title}</span>)}
      </div>
    </div>
  );
  return (
    <section className="mt-7">
      <h4 className={H4}>{t("tools")}</h4>
      {group(t("readOnlyTools"), rows.filter((r) => !r.writes))}
      {group(t("writeTools"), rows.filter((r) => r.writes))}
    </section>
  );
}

// Connected: read-only tools run; anything that writes asks — until the person says otherwise,
// per tool or per group.
function Permissions({ c, api, rows, setRows }: { c: Connector; api: ChatApi["api"]; rows: ToolRow[]; setRows: (r: ToolRow[]) => void }) {
  const set = (names: string[], mode: Mode, scope: "tool" | "group") => {
    const next = rows.map((r) => (names.includes(r.name) ? { ...r, mode } : r));
    setRows(next);
    const chosen = next.filter((r) => r.mode !== (r.writes ? "ask" : "allow"));   // only what differs from the default: an untouched tool follows the composer's switch
    api(`/connectors/${c.name}/tools`, { method: "PUT", json: { tools: Object.fromEntries(chosen.map((r) => [r.name, r.mode])) } }).catch(() => {});
    track("connector_permissions_changed", { connector: c.name, scope, to: mode });
  };
  const group = (title: string, list: ToolRow[]) => list.length > 0 && (
    <div className="mb-4 last:mb-0">
      <div className="mb-1.5 flex items-center justify-between gap-3">
        <p className="flex items-center gap-2 text-sm text-foreground">{title}<span className="rounded-md bg-secondary px-1.5 text-[11px] text-muted-foreground">{list.length}</span></p>
        <select value={list.every((r) => r.mode === list[0].mode) ? list[0].mode : ""} onChange={(e) => e.target.value && set(list.map((r) => r.name), e.target.value as Mode, "group")}
          className="cursor-pointer rounded-lg border border-border bg-background px-2 py-1 text-xs text-foreground">
          <option value="" disabled hidden>—</option>
          <option value="allow" title={t("hintAllow")}>{t("alwaysAllow")}</option>
          <option value="ask" title={t("hintAsk")}>{t("needsApproval")}</option>
          <option value="never" title={t("hintNever")}>{t("never")}</option>
        </select>
      </div>
      <div className={CARD}>
        {list.map((r) => (
          <div key={r.name} className="flex items-center justify-between gap-4 border-b border-border/60 py-2.5 text-sm last:border-0">
            <div className="min-w-0">
              <p className="truncate text-foreground">{r.title}</p>
              {r.description && <p className="truncate text-xs text-muted-foreground"><bdi>{r.description}</bdi></p>}
            </div>
            <div className="flex shrink-0 rounded-lg border border-border bg-secondary p-0.5">
              {MODES.map((m) => (
                <button key={m} title={t(MODE_HINT[m])} onClick={() => set([r.name], m, "tool")} className={cn("cursor-pointer rounded-md px-2 py-0.5 text-[11px] transition-colors", r.mode === m ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}>{t(m)}</button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
  return (
    <section className="mt-7">
      <h4 className={cn(H4, "mb-1")}>{t("toolPermissions")}</h4>
      <p className="mb-3 text-xs text-muted-foreground">{t("toolPermissionsSub")}</p>
      {group(t("readOnlyTools"), rows.filter((r) => !r.writes))}
      {group(t("writeTools"), rows.filter((r) => r.writes))}
    </section>
  );
}
