// The connector directory and a connector's page (docs/notes/plugins-connectors.md, UI).
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Icon } from "./icon";
import type { ChatApi } from "../hooks/use-chat";
import { t, useLang } from "../lib/i18n";
import { cn } from "../lib/utils";
import { track } from "../lib/analytics";

export type Connector = {
  name: string; title: string | null; scope: "user" | "workspace" | "either"; kind: "oauth" | "key"; hint: string | null;
  connected: boolean; connected_as: "user" | "workspace" | null;
  admin: boolean; allowed: boolean; org_admin: boolean; team: string | null;
  description: string | null; about: string | null; icon: string | null;
  prompts: string[]; use_cases: [string, string][]; skills: [string, string][];
  developer: string | null; category: string | null; website: string | null; version: string | null;
  privacy: string | null; terms: string | null; docs: string | null; support: string | null;
  servers: { label: string; url: string }[];
};
type Mode = "allow" | "ask" | "never";
type ToolRow = { name: string; title: string; description: string | null; writes: boolean; mode: Mode };
type PromptRow = { name: string; title: string; description: string | null };
const MODES: Mode[] = ["allow", "ask", "never"];
const MODE_HINT = { allow: "hintAllow", ask: "hintAsk", never: "hintNever" } as const;

export const connectorLabel = (c: { name: string; title?: string | null }) =>
  c.title || c.name.charAt(0).toUpperCase() + c.name.slice(1);

// The declared logo, else the site's favicon, else a link glyph — a connector always has a face.
export function ConnectorIcon({ c, className = "size-9" }: { c: Connector; className?: string }) {
  const host = c.website?.replace(/^https?:\/\//, "").split("/")[0];
  const src = c.icon || (host ? `https://www.google.com/s2/favicons?sz=128&domain=${host}` : null);
  return src
    ? <span className={cn(className, "flex shrink-0 items-center justify-center overflow-hidden rounded-xl border border-border/60 bg-white")}><img src={src} alt="" className="size-[68%] object-contain" /></span>
    : <span className={cn(className, "flex shrink-0 items-center justify-center rounded-xl bg-secondary text-muted-foreground")}><Icon name="link" className="size-1/2" /></span>;
}

// cycls.com's ember, each stop mixed into the theme background so it reads in light and dark alike.
const PANEL = "radial-gradient(140% 120% at 96% 100%, color-mix(in oklab, #ffbe6e 42%, var(--color-background)) 0%, color-mix(in oklab, #ff8c37 36%, var(--color-background)) 20%, color-mix(in oklab, #d6501e 28%, var(--color-background)) 42%, color-mix(in oklab, #962d14 18%, var(--color-background)) 66%, var(--color-background) 100%)";

const RAIL = ["connectors", "plugins", "skills"] as const;
const H4 = "mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground";
const CARD = "rounded-xl border border-border bg-background/40 px-4";
const CHIP = "rounded-full border border-border bg-secondary/50 px-2.5 py-1 text-xs text-foreground";

export function ConnectorsDialog({ api, items, reload, initial, onClose, onUsePrompt }: {
  api: ChatApi["api"];
  items: Connector[] | null;
  reload: () => void;
  initial?: string;
  onClose: () => void;
  onUsePrompt: (text: string, c: Connector) => void;
}) {
  const isAr = useLang() === "ar";
  const [tab, setTab] = useState<"discover" | "yours">("discover");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<string | null>(initial ?? null);

  const connect = async (c: Connector, scope: "user" | "workspace") => {
    track("connector_connect_clicked", { connector: c.name, source: "directory", scope });
    const { url } = await (await api(`/connectors/${c.name}/authorize?scope=${scope}`, { method: "POST" })).json();
    window.open(url, "_blank", "noopener");
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

  const q = query.trim().toLowerCase();
  const list = (items ?? [])
    .filter((c) => c.connected === (tab === "yours"))
    .filter((c) => !q || connectorLabel(c).toLowerCase().includes(q) || (c.description ?? "").toLowerCase().includes(q));
  const detail = open ? items?.find((c) => c.name === open) : null;

  const tabs = (
    <div className="flex shrink-0 rounded-lg border border-border bg-secondary p-0.5">
      {(["discover", "yours"] as const).map((k) => (
        <button key={k} onClick={() => setTab(k)} className={cn("cursor-pointer rounded-md px-3 py-1 text-xs transition-colors", tab === k ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}>
          {t(k)}
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

  const grid = items === null ? null : list.length === 0 ? (
    <div className="flex flex-col items-center py-20 text-center text-muted-foreground">
      <Icon name="link" className="mb-3 size-8 opacity-30" strokeWidth={1.5} />
      <p className="text-sm">{q ? t("noConnectorsFound") : tab === "yours" ? t("nothingConnected") : t("noConnectors")}</p>
      {!q && tab === "yours" && <p className="mt-1 text-xs">{t("nothingConnectedSub")}</p>}
    </div>
  ) : (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {list.map((c) => (
        <button key={c.name} onClick={() => setOpen(c.name)} className={cn("flex cursor-pointer flex-col gap-3 rounded-2xl border border-border bg-background/40 p-4 text-start transition hover:border-foreground/25 hover:shadow-sm", !c.allowed && "opacity-50")}>
          <div className="flex items-center gap-3">
            <ConnectorIcon c={c} className="size-10" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-foreground">{connectorLabel(c)}</p>
              {c.category && <p className="truncate text-[11px] text-muted-foreground">{c.category}</p>}
            </div>
            {!c.allowed
              ? <span className="rounded-full border border-border px-1.5 py-px text-[10px] text-muted-foreground">{t("off")}</span>
              : c.connected
                ? <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground"><span className="size-2 rounded-full bg-green-500" />{t("connectedLabel")}</span>
                : <span className="flex size-7 items-center justify-center rounded-full border border-border text-muted-foreground"><Icon name="plus" className="size-3.5" /></span>}
          </div>
          {c.description && <p className="line-clamp-2 text-xs leading-relaxed text-muted-foreground"><bdi>{c.description}</bdi></p>}
        </button>
      ))}
    </div>
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
              <Detail c={detail} api={api} onBack={() => setOpen(null)} onConnect={connect} onSaveKey={saveKey} onDisconnect={disconnect} onAllow={allow} onPrompt={usePrompt} />
            ) : (
              <>
                <div className="mb-5 hidden sm:block">
                  <h2 className="text-lg font-semibold text-foreground">{t("connectors")}</h2>
                  <p className="text-sm text-muted-foreground">{t("connectorsSub")}</p>
                </div>
                <div className="mb-5 flex items-center gap-3">{search}{tabs}</div>
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

function Switch({ on, onChange }: { on: boolean; onChange: (on: boolean) => void }) {
  return (
    <button role="switch" aria-checked={on} onClick={() => onChange(!on)} className={cn("relative h-5 w-9 shrink-0 cursor-pointer rounded-full transition-colors", on ? "bg-foreground" : "bg-muted-foreground/30")}>
      <span className={cn("absolute top-0.5 size-4 rounded-full bg-background shadow-sm transition-all", on ? "start-4.5" : "start-0.5")} />
    </button>
  );
}

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
    <form onSubmit={(e) => { e.preventDefault(); if (key.trim()) onSave(key.trim(), scope); }} className="flex shrink-0 flex-wrap items-center gap-2">
      <input type="password" value={key} onChange={(e) => setKey(e.target.value)} placeholder={c.hint ?? t("apiKey")} autoComplete="off" dir="ltr"
        className="w-44 rounded-full border border-border bg-background px-3.5 py-2 text-sm outline-none placeholder:text-muted-foreground focus:border-foreground/30" />
      {choice && (
        <select value={scope} onChange={(e) => setScope(e.target.value as "user" | "workspace")} className="cursor-pointer rounded-full border border-border bg-background px-2.5 py-2 text-xs text-foreground">
          <option value="user">{t("forMe")}</option>
          <option value="workspace">{t("forTeam").replace("{name}", team ?? "")}</option>
        </select>
      )}
      <button type="submit" disabled={!key.trim()} className="shrink-0 cursor-pointer rounded-full bg-foreground px-4 py-2 text-sm font-medium text-background transition hover:opacity-80 disabled:cursor-default disabled:opacity-40">{t("save")}</button>
    </form>
  );
}

function Detail({ c, api, onBack, onConnect, onSaveKey, onDisconnect, onAllow, onPrompt }: {
  c: Connector;
  api: ChatApi["api"];
  onBack: () => void;
  onConnect: (c: Connector, scope: "user" | "workspace") => void;
  onSaveKey: (c: Connector, key: string, scope: "user" | "workspace") => void;
  onDisconnect: (c: Connector) => void;
  onAllow: (c: Connector, on: boolean) => void;
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
  const facts = [[t("capabilities"), caps], [t("developer"), c.developer], [t("category"), c.category]].filter(([, v]) => v) as [string, string][];
  const links = [[t("website"), c.website], [t("privacyPolicy"), c.privacy], [t("termsLabel"), c.terms], [t("documentation"), c.docs]].filter(([, v]) => v) as [string, string][];

  return (
    <div>
      <button onClick={onBack} className="mb-5 flex cursor-pointer items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
        <Icon name="chevron-left" className="size-3.5 rtl:rotate-180" />{t("back")}
      </button>

      <div className="flex flex-wrap items-start gap-4">
        <ConnectorIcon c={c} className="size-16" />
        <div className="min-w-0 flex-1 pt-0.5">
          <h3 className="text-xl font-semibold leading-tight text-foreground">{label}</h3>
          {c.category && <p className="text-xs text-muted-foreground">{c.category}</p>}
          {c.description && <p className="mt-1.5 text-sm text-muted-foreground"><bdi>{c.description}</bdi></p>}
        </div>
        {action}
      </div>
      {status && <p className="mt-3 flex items-center gap-2 text-xs text-muted-foreground"><span className={cn("size-2 rounded-full", status[0])} />{status[1]}</p>}

      {c.org_admin && (
        <div className="mt-5 flex items-center justify-between gap-4 rounded-xl border border-border bg-background/40 px-4 py-3">
          <div className="min-w-0">
            <p className="text-sm text-foreground">{t("allowedInOrg")}</p>
            <p className="text-xs text-muted-foreground">{t("allowedInOrgSub")}</p>
          </div>
          <Switch on={c.allowed} onChange={(on) => onAllow(c, on)} />
        </div>
      )}

      {c.about && <p className="mt-6 text-sm leading-relaxed text-foreground/90"><bdi>{c.about}</bdi></p>}

      {c.prompts.length > 0 && (
        <section className="mt-7">
          <h4 className={H4}>{t("tryAsking")}</h4>
          <div className="flex flex-col gap-2.5 rounded-3xl p-3 sm:p-4" style={{ backgroundImage: PANEL }}>
            {c.prompts.map((p) => (
              <button key={p} onClick={() => onPrompt(c, p)} className="flex w-full cursor-pointer items-center gap-4 rounded-2xl border border-border/50 bg-background/80 px-5 py-3.5 text-start shadow-sm backdrop-blur transition hover:bg-background">
                <span className="min-w-0 flex-1 text-[15px] leading-snug text-foreground"><b className="font-semibold">@{label}</b> <bdi>{p}</bdi></span>
                <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-secondary text-foreground"><Icon name="arrow-right" className="size-4 rtl:rotate-180" /></span>
              </button>
            ))}
          </div>
        </section>
      )}

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
