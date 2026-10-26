// The Apps section of the connectors window (docs/notes/apps.md, "The catalog"): the agent's catalog
// with what this workspace has installed, and the workspace's app theme. Same shapes as the
// Connectors list beside it — search, category chips, two-column cards, one 28px state slot.
import { useEffect, useMemo, useState } from "react";
import { Icon } from "./icon";
import { PLATE } from "./connectors-dialog";
import type { ChatApi } from "../hooks/use-chat";
import { t, getLang } from "../lib/i18n";
import { cn } from "../lib/utils";
import { track } from "../lib/analytics";
import {
  BASES, COLORS, RADII, SWATCH, DEFAULT_CHOICE, isHex, normalize, setAppTheme, themeTokens,
  type AppThemeChoice, type Tokens,
} from "../lib/app-theme";

type Api = ChatApi["api"];
export type CatalogApp = {
  slug: string; name: string; name_ar?: string; icon?: string;
  description?: string; description_ar?: string; category?: string; category_ar?: string;
  version: string; bytes: number; state: "available" | "installed" | "update" | "conflict"; installed_name?: string;
};

const H4 = "mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground";
const PILL = "shrink-0 cursor-pointer rounded-full px-3.5 py-1.5 text-xs font-medium transition hover:opacity-80 disabled:cursor-default disabled:opacity-40";
const SOLID = cn(PILL, "bg-foreground text-background");
const LINE = cn(PILL, "border border-border text-foreground");

const ar = () => getLang() === "ar";
export const appName = (a: CatalogApp) => a.installed_name || (ar() && a.name_ar) || a.name;
const about = (a: CatalogApp) => (ar() && a.description_ar) || a.description || "";
const category = (a: CatalogApp) => (ar() && a.category_ar) || a.category || "";
const kb = (n: number) => `${Math.max(1, Math.round(n / 1024)).toLocaleString(ar() ? "ar" : "en")} KB`;

function Glyph({ a, className = "size-10" }: { a: CatalogApp; className?: string }) {
  const img = a.icon?.startsWith("data:image/");
  return (
    <span className={cn(className, "flex shrink-0 items-center justify-center text-xl", PLATE)}>
      {img ? <img src={a.icon} alt="" className="size-[68%] object-contain" />
        : a.icon && [...a.icon].length <= 2 ? <span aria-hidden>{a.icon}</span>
        : <span className="text-sm font-semibold text-foreground">{[...appName(a)][0]?.toUpperCase()}</span>}
    </span>
  );
}

export function AppsCatalog({ api, onOpen, onChanged, initialView = "browse" }: {
  api: Api;
  onOpen: (entry: string, name: string) => void;   // apps/<slug>/index.html, in the canvas
  onChanged?: () => void;                          // the Apps tab and the + menu re-list
  initialView?: "browse" | "theme";
}) {
  const [view, setView] = useState(initialView);
  return (
    <>
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <div className="hidden min-w-0 flex-1 sm:block">
          <h2 className="font-display text-lg font-semibold text-foreground">{t("apps")}</h2>
          <p className="text-sm text-muted-foreground">{view === "theme" ? t("themeSub") : t("appsSub")}</p>
        </div>
        <div className="flex shrink-0 rounded-full border border-border bg-secondary p-0.5" role="tablist">
          {(["browse", "theme"] as const).map((k) => (
            <button key={k} role="tab" aria-selected={view === k} onClick={() => setView(k)}
              className={cn("cursor-pointer rounded-full px-3.5 py-1 text-xs transition-colors",
                view === k ? "bg-background font-medium text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}>
              {t(k === "browse" ? "appsBrowseTab" : "appsThemeTab")}
            </button>
          ))}
        </div>
      </div>
      {view === "browse" ? <Browse api={api} onOpen={onOpen} onChanged={onChanged} /> : <ThemePanel api={api} />}
    </>
  );
}

function Browse({ api, onOpen, onChanged }: { api: Api; onOpen: (entry: string, name: string) => void; onChanged?: () => void }) {
  const [data, setData] = useState<{ apps: CatalogApp[]; admin: boolean } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [cat, setCat] = useState<string | null>(null);
  const load = () => api("/apps/catalog", { silent: true }).then((r) => r.json()).then(setData).catch(() => setData({ apps: [], admin: false }));
  useEffect(() => { load(); }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (a: CatalogApp, what: "install" | "update" | "uninstall") => {
    if (what === "uninstall" && !confirm(t("removeAppConfirm").replace("{name}", appName(a)))) return;
    setBusy(a.slug);
    try {
      await api(`/apps/${what}`, { method: "POST", json: { slug: a.slug } });
      track("app_catalog_action", { app: a.slug, action: what });
      onChanged?.();
      if (what === "install") onOpen(`apps/${a.slug}/index.html`, appName(a));
    } catch { /* the api's own toast says what failed */ }
    finally { setBusy(null); load(); }
  };

  const q = query.trim().toLowerCase();
  const all = data?.apps ?? [];
  const cats = useMemo(() => [...new Set(all.map(category).filter(Boolean))].sort(), [all]);   // eslint-disable-line react-hooks/exhaustive-deps
  const matches = all.filter((a) =>
    (!q || [a.name, a.name_ar, a.description, a.description_ar, a.slug].some((f) => f?.toLowerCase().includes(q)))
    && (!cat || category(a) === cat));
  const mine = matches.filter((a) => a.state === "installed" || a.state === "update");
  const rest = matches.filter((a) => a.state === "available" || a.state === "conflict");

  const card = (a: CatalogApp) => {
    const has = a.state === "installed" || a.state === "update";
    const admin = !!data?.admin;
    return (
      <div key={a.slug} data-app={a.slug} className="flex flex-col gap-3 rounded-2xl border border-border bg-background/40 p-4 text-start">
        <div className="flex items-center gap-3">
          <Glyph a={a} />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-foreground"><bdi>{appName(a)}</bdi></p>
            <p className="truncate text-[11px] text-muted-foreground">{[category(a), kb(a.bytes)].filter(Boolean).join(" · ")}</p>
          </div>
          {/* The connectors' 28px state slot: + to install, a check once it is here, the update dot. */}
          {a.state === "update"
            ? <span title={t("updateAvailable")} className="flex size-7 shrink-0 items-center justify-center rounded-full bg-amber-500/15 text-amber-600"><Icon name="refresh" className="size-3.5" strokeWidth={2.5} /></span>
            : has
              ? <span title={t("installedApp")} className="flex size-7 shrink-0 items-center justify-center rounded-full bg-green-500/15 text-green-600"><Icon name="check" className="size-3.5" strokeWidth={2.5} /></span>
              : <span title={t("installApp")} className="flex size-7 shrink-0 items-center justify-center rounded-full border border-border text-muted-foreground"><Icon name="plus" className="size-3.5" /></span>}
        </div>
        {about(a) && <p className="line-clamp-2 text-xs leading-relaxed text-muted-foreground"><bdi>{about(a)}</bdi></p>}
        <div className="mt-auto flex flex-wrap items-center gap-2">
          {a.state === "update" && <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[11px] font-medium text-amber-700 dark:text-amber-400">{t("updateAvailable")}</span>}
          {a.state === "conflict" && <span className="text-[11px] text-muted-foreground">{t("appTaken")}</span>}
          <span className="ms-auto flex gap-2">
            {has && <button onClick={() => onOpen(`apps/${a.slug}/index.html`, appName(a))} className={LINE}>{t("open")}</button>}
            {has && admin && <button disabled={busy === a.slug} onClick={() => act(a, "uninstall")} className={LINE} aria-label={`${t("remove")} ${appName(a)}`}>{t("remove")}</button>}
            {a.state === "update" && admin && <button disabled={busy === a.slug} onClick={() => act(a, "update")} className={SOLID}>{t("updateApp")}</button>}
            {a.state === "available" && admin && <button disabled={busy === a.slug} onClick={() => act(a, "install")} className={SOLID}>{t("installApp")}</button>}
          </span>
        </div>
      </div>
    );
  };

  return (
    <>
      <div className="relative mb-4 min-w-0">
        <Icon name="search" className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("searchApps")} dir="auto"
          className="w-full rounded-xl border border-border bg-background py-2 pe-3 ps-9 text-sm outline-none placeholder:text-muted-foreground focus:border-foreground/30" />
      </div>
      {cats.length > 1 && (
        <div className="-mx-1 mb-4 flex gap-1.5 overflow-x-auto px-1 pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {[null, ...cats].map((k) => (
            <button key={k ?? "all"} onClick={() => setCat(k)}
              className={cn("shrink-0 cursor-pointer rounded-full border px-3 py-1 text-xs transition-colors",
                cat === k ? "border-foreground bg-foreground text-background" : "border-border text-muted-foreground hover:text-foreground")}>
              {k ?? t("allApps")}
            </button>
          ))}
        </div>
      )}
      {data && !data.admin && <p className="mb-4 flex items-center gap-2 text-xs text-muted-foreground">{t("appsAdminOnly")}</p>}
      {data === null ? null : matches.length === 0 ? (
        <div className="flex flex-col items-center py-20 text-center text-muted-foreground">
          <Icon name="grid" className="mb-3 size-8 opacity-30" strokeWidth={1.5} />
          <p className="text-sm">{q || cat ? t("noAppsFound") : t("noApps")}</p>
        </div>
      ) : (
        <>
          {mine.length > 0 && <section className="mb-6"><h4 className={H4}>{t("yours")}</h4><div className="grid grid-cols-1 gap-3 sm:grid-cols-2">{mine.map(card)}</div></section>}
          {rest.length > 0 && <section>{mine.length > 0 && <h4 className={H4}>{t("discover")}</h4>}<div className="grid grid-cols-1 gap-3 sm:grid-cols-2">{rest.map(card)}</div></section>}
        </>
      )}
    </>
  );
}

// ---- Theme -----------------------------------------------------------------------------------

const same = (a: AppThemeChoice | null, b: AppThemeChoice | null) => JSON.stringify(a) === JSON.stringify(b);

export function ThemePanel({ api }: { api: Api }) {
  const [saved, setSaved] = useState<AppThemeChoice | null>(null);
  const [fallback, setFallback] = useState<AppThemeChoice | null>(null);
  const [admin, setAdmin] = useState(false);
  const [draft, setDraft] = useState<AppThemeChoice>(DEFAULT_CHOICE);
  const [hex, setHex] = useState("");
  useEffect(() => {
    api("/apps/theme", { silent: true }).then((r) => r.json()).then((d) => {
      const mine = normalize(d.theme), def = normalize(d.default);
      setSaved(mine); setFallback(def); setAdmin(!!d.admin);
      const start = mine ?? def ?? DEFAULT_CHOICE;
      setDraft(start); setHex(start.primary ?? "");
    }).catch(() => {});
  }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  const set = (patch: Partial<AppThemeChoice>) => setDraft((d) => {
    const next = { ...d, ...patch };
    if (!next.primary) delete next.primary;
    return next;
  });
  const save = async () => {
    await api("/apps/theme", { method: "PUT", json: { theme: draft } });
    setSaved(draft); setAppTheme(draft);   // every open app re-skins now (canvas → cycls:command theme)
    track("app_theme_saved", { base: draft.base, color: draft.color, radius: draft.radius, brand: !!draft.primary });
  };
  const reset = async () => {
    await api("/apps/theme", { method: "PUT", json: { theme: null } });
    setSaved(null); setAppTheme(fallback);
    const start = fallback ?? DEFAULT_CHOICE;
    setDraft(start); setHex(start.primary ?? "");
  };
  const tokens = themeTokens(draft);
  const dirty = !same(draft, saved ?? fallback ?? null) || saved === null;
  const row = "mb-6";
  const swatch = (on: boolean) => cn("flex cursor-pointer items-center gap-2 rounded-full border px-2.5 py-1 text-xs transition-colors disabled:cursor-default",
    on ? "border-foreground text-foreground" : "border-border text-muted-foreground hover:text-foreground");

  return (
    <div>
      {!admin && <p className="mb-4 flex items-center gap-2 text-xs text-muted-foreground">{t("themeAdminOnly")}</p>}
      <fieldset disabled={!admin} className="min-w-0">
        <section className={row}>
          <h4 className={H4}>{t("themeBase")}</h4>
          <div className="flex flex-wrap gap-2">
            {BASES.map((b) => (
              <button key={b} onClick={() => set({ base: b })} className={swatch(draft.base === b)} aria-pressed={draft.base === b}>
                <span className="size-3.5 rounded-full border border-black/10" style={{ background: SWATCH[b] }} />{b[0].toUpperCase() + b.slice(1)}
              </button>
            ))}
          </div>
        </section>
        <section className={row}>
          <h4 className={H4}>{t("themeColor")}</h4>
          <div className="flex flex-wrap gap-2">
            {COLORS.map((c) => (
              <button key={c} onClick={() => { set({ color: c, primary: undefined }); setHex(""); }} className={swatch(draft.color === c && !draft.primary)} aria-pressed={draft.color === c && !draft.primary}>
                <span className="size-3.5 rounded-full border border-black/10" style={{ background: c === "base" ? SWATCH[draft.base] : SWATCH[c] }} />
                {c === "base" ? t("themeColorBase") : c[0].toUpperCase() + c.slice(1)}
              </button>
            ))}
          </div>
        </section>
        <section className={row}>
          <h4 className={H4}>{t("themeRadius")}</h4>
          <div className="flex flex-wrap gap-2" dir="ltr">
            {RADII.map((r) => (
              <button key={r} onClick={() => set({ radius: r })} className={cn(swatch(draft.radius === r), "font-mono")} aria-pressed={draft.radius === r}>{r}</button>
            ))}
          </div>
        </section>
        <section className={row}>
          <h4 className={cn(H4, "mb-1")}>{t("themeBrand")}</h4>
          <p className="mb-2 text-xs text-muted-foreground">{t("themeBrandSub")}</p>
          <div className="flex items-center gap-2" dir="ltr">
            <input type="color" aria-label={t("themeBrand")} value={isHex(draft.primary) ? draft.primary : "#0b6b5d"}
              onChange={(e) => { setHex(e.target.value); set({ primary: e.target.value }); }}
              className="h-9 w-12 cursor-pointer rounded-lg border border-border bg-background p-1" />
            <input value={hex} placeholder="#0b6b5d" spellCheck={false}
              onChange={(e) => { setHex(e.target.value); if (isHex(e.target.value)) set({ primary: e.target.value.toLowerCase() }); }}
              className="h-9 w-28 rounded-full border border-border bg-background px-3 font-mono text-sm text-foreground outline-none focus:border-foreground/30" />
            {draft.primary && <button onClick={() => { setHex(""); set({ primary: undefined }); }} className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">{t("themeBrandClear")}</button>}
          </div>
        </section>
      </fieldset>

      <section className={row}>
        <h4 className={H4}>{t("preview")}</h4>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Preview tokens={tokens.light} label={t("light")} />
          <Preview tokens={tokens.dark} label={t("dark")} />
        </div>
        {saved === null && <p className="mt-2 text-xs text-muted-foreground">{t("themeApps")}</p>}
      </section>

      {admin && (
        <div className="flex items-center justify-end gap-2">
          {saved && <button onClick={reset} className={LINE}>{t("themeReset")}</button>}
          <button onClick={save} disabled={!dirty} className={SOLID}>{t("save")}</button>
        </div>
      )}
    </div>
  );
}

// A small shadcn card, button, badge and table in the chosen tokens — what an app will look like.
// The tokens are set on the frame, and everything inside reads them, as an app's Tailwind classes do.
export function Preview({ tokens, label }: { tokens: Tokens; label: string }) {
  const v = (k: string) => `var(${k})`;
  const r = (m = 1) => `calc(var(--radius) * ${m})`;
  const rows: [string, string, boolean][] = [["Al Noor Trading", "12,400", true], ["Riyadh Logistics", "8,950", false]];
  return (
    <div data-preview={label} style={{ ...(tokens as React.CSSProperties), background: v("--background"), color: v("--foreground"), borderRadius: r(1.6) }}
      className="border border-border p-3">
      <p className="mb-2 text-[11px] text-muted-foreground">{label}</p>
      <div style={{ background: v("--card"), color: v("--card-foreground"), border: `1px solid ${v("--border")}`, borderRadius: r(1.4) }} className="p-3">
        <div className="mb-2 flex items-center justify-between gap-2">
          <span className="text-sm font-semibold">{t("previewInvoice")} #1042</span>
          <span style={{ background: v("--secondary"), color: v("--secondary-foreground"), borderRadius: r(0.8) }} className="px-2 py-0.5 text-[11px]">{t("previewDue")}</span>
        </div>
        <table className="mb-3 w-full text-start text-xs">
          <thead><tr style={{ color: v("--muted-foreground") }}><th className="pb-1 text-start font-normal">{t("previewClient")}</th><th className="pb-1 text-end font-normal">{t("previewAmount")}</th></tr></thead>
          <tbody>
            {rows.map(([who, amt, paid]) => (
              <tr key={who} style={{ borderTop: `1px solid ${v("--border")}` }}>
                <td className="py-1.5">{who} {paid && <span style={{ background: v("--primary"), color: v("--primary-foreground"), borderRadius: r(0.6) }} className="ms-1 px-1.5 text-[10px]">{t("previewPaid")}</span>}</td>
                <td className="py-1.5 text-end tabular-nums">{amt}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="flex gap-2">
          <span style={{ background: v("--primary"), color: v("--primary-foreground"), borderRadius: r() }} className="px-3 py-1.5 text-xs font-medium">{t("previewPay")}</span>
          <span style={{ border: `1px solid ${v("--input")}`, borderRadius: r() }} className="px-3 py-1.5 text-xs">{t("cancel")}</span>
        </div>
      </div>
    </div>
  );
}
