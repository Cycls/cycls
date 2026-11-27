// Ready-made apps (docs/notes/apps.md, "Ready-made apps"): the Apps panel's store while a workspace has none of its own,
// and the gallery beside connectors and skills, where each one is seen before it is installed, and the look they wear.
import { useState, type CSSProperties, type ReactNode } from "react";
import { AppTile } from "./app-icon";
import { Icon } from "./icon";
import { GlowStar, Star } from "./cycls-star";
import { t, getLang } from "../lib/i18n";
import { cn } from "../lib/utils";
import { LOOKS, lookTokens, type Look, type Tokens } from "../lib/app-look";

type Two = { en: string; ar: string };
export type Offered = {
  slug: string; title: Two; description: Two; category: Two; icon?: string; picture?: string; featured?: boolean;
  state: "available" | "installed" | "update" | "changed" | "taken";
};
export type Catalog = { apps: Offered[]; admin: boolean };
export type StoreActions = {
  agent: string;
  busy: string | null;   // the slug being installed
  onPeek: (a: Offered) => void;
  onInstall: (a: Offered) => void;
  onBuild: (idea?: string) => void;
};

const say = (x?: Two) => (getLang() === "ar" ? x?.ar || x?.en : x?.en || x?.ar) || "";
const face = (a: Offered) => ({ slug: a.slug, name: say(a.title), letter: [...say(a.title)][0],
  iconSrc: a.icon?.startsWith("<svg") ? `data:image/svg+xml;utf8,${encodeURIComponent(a.icon)}` : undefined });
const PILL = "inline-flex shrink-0 cursor-pointer items-center gap-1.5 rounded-full px-3.5 py-1.5 text-xs font-medium transition hover:opacity-80 disabled:cursor-default disabled:opacity-60";
const SOLID = cn(PILL, "bg-foreground text-background");
const LINE = cn(PILL, "border border-border text-foreground");
// The brand's dark satin and its grain, for what is featured.
const SATIN: CSSProperties = { backgroundImage: "url(/brand/satin-dark.jpg)", backgroundSize: "cover", backgroundPosition: "center" };
const Grain = () => <span aria-hidden className="pointer-events-none absolute inset-0 opacity-20 mix-blend-overlay" style={{ backgroundImage: "url(/brand/grain.png)" }} />;
const install = (a: Offered, s: StoreActions, className = SOLID) => (
  <button onClick={(e) => { e.stopPropagation(); s.onInstall(a); }} disabled={!!s.busy} className={className}>
    {s.busy === a.slug ? t("appInstalling") : a.state === "update" ? t("appUpdate") : t("appInstall")}
  </button>
);

// The app as a page on the gallery's grey tile, tilted until hovered (examples.tsx: Tile).
function Picture({ src }: { src?: string }) {
  return (
    <span className="relative flex aspect-[16/10] w-full items-center justify-center overflow-hidden rounded-xl border border-black/[.07] bg-[#e1e1e1] dark:border-white/[.06] dark:bg-[#222]">
      {src && <img src={src} alt="" loading="lazy" draggable={false}
        className="h-auto w-[86%] translate-y-[5%] rotate-[-4deg] shadow-[3px_5px_9px_#0003] transition-[translate,rotate] duration-200 group-hover:translate-y-[2%] group-hover:rotate-[-1deg]" />}
    </span>
  );
}

export function BuildButton({ agent, onBuild }: { agent: string; onBuild: () => void }) {
  return (
    <button onClick={onBuild} className="flex w-full cursor-pointer items-center justify-center gap-2 rounded-full border border-border py-2 text-sm font-medium text-foreground transition hover:bg-secondary/60">
      <GlowStar size={15} />{t("appsBuild").replace("{agent}", agent)}
    </button>
  );
}

// The Apps panel of a workspace with no app yet: one featured, a few picks, the rest in the gallery.
export function AppsStore({ catalog, actions, onGallery }: { catalog: Catalog; actions: StoreActions; onGallery: () => void }) {
  const offered = catalog.apps.filter((a) => a.state === "available");
  const hero = offered.find((a) => a.featured) ?? offered[0];
  if (!hero) return null;
  return (
    <div className="px-3 py-4">
      <div role="button" onClick={() => actions.onPeek(hero)} style={SATIN}
        className="group relative cursor-pointer overflow-hidden rounded-2xl bg-black text-white ring-1 ring-white/10">
        <Grain />
        <div className="relative flex items-start gap-3 p-4">
          <AppTile app={face(hero)} className="size-11 rounded-xl bg-white text-black" textClassName="text-lg" />
          <span className="min-w-0 flex-1">
            <span className="block text-[11px] text-white/50">{t("appsFeatured")}</span>
            <span className="block font-display text-base font-semibold leading-snug"><bdi>{say(hero.title)}</bdi></span>
            <span className="block text-xs leading-5 text-white/70"><bdi>{say(hero.description)}</bdi></span>
          </span>
          {catalog.admin && install(hero, actions, cn(PILL, "bg-white px-3.5 py-1 font-semibold text-black"))}
        </div>
        {hero.picture && (
          <div className="relative h-32 overflow-hidden">
            <img src={hero.picture} alt="" draggable={false}
              className="absolute start-[8%] top-1 w-[84%] rotate-[-4deg] rounded-[3px] shadow-[3px_5px_14px_#0009] transition-[translate,rotate] duration-200 group-hover:-translate-y-1 group-hover:rotate-[-2deg]" />
          </div>
        )}
      </div>
      <div className="mt-3"><BuildButton agent={actions.agent} onBuild={() => actions.onBuild()} /></div>
      <div className="flex items-center justify-between px-1 pb-1 pt-5">
        <p className="text-xs font-medium text-muted-foreground">{t("appsPicks")}</p>
        <button onClick={onGallery} className="flex cursor-pointer items-center gap-1 text-xs font-medium text-foreground hover:opacity-70">
          {t("appsAll")}<Icon name="arrow-right" className="size-3.5 rtl:-scale-x-100" />
        </button>
      </div>
      {offered.filter((a) => a !== hero).slice(0, 5).map((a) => (
        <div key={a.slug} role="button" onClick={() => actions.onPeek(a)} className="flex cursor-pointer items-center gap-3 rounded-xl px-1 py-2 hover:bg-secondary/60">
          <AppTile app={face(a)} className="size-11" textClassName="text-lg" />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[13px] font-medium text-foreground"><bdi>{say(a.title)}</bdi></span>
            <span className="block truncate text-[11px] text-muted-foreground"><bdi>{say(a.description)}</bdi></span>
          </span>
          {catalog.admin && install(a, actions, cn(SOLID, "px-3 py-1"))}
        </div>
      ))}
    </div>
  );
}

// The gallery, the third part of the window that lists connectors and skills.
export function AppsGallery({ catalog, actions, onOpen, onRemove, look, onLook }: {
  catalog: Catalog; actions: StoreActions; onOpen: (a: Offered) => void; onRemove: (a: Offered) => void;
  look: Look | null; onLook: (look: Look) => Promise<void>;
}) {
  const [view, setView] = useState<"apps" | "look">("apps");
  const [query, setQuery] = useState("");
  const [cat, setCat] = useState<string | null>(null);
  const cats = [...new Map(catalog.apps.filter((a) => a.category.en).map((a) => [a.category.en, a.category])).values()];
  const q = query.trim().toLowerCase();
  const shown = catalog.apps.filter((a) => (!cat || a.category.en === cat)
    && (!q || [a.title.en, a.title.ar, a.description.en, a.description.ar].some((s) => s?.toLowerCase().includes(q))));
  const chip = (on: boolean) => cn("cursor-pointer rounded-full px-3 py-1 text-sm transition-colors", on ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground");
  return (
    <>
      <div style={SATIN} className="relative mb-5 overflow-hidden rounded-2xl bg-black px-6 py-7 text-white">
        <Grain />
        <p className="relative font-display text-2xl font-semibold">{t("appsHeadline")}</p>
        <p className="relative mt-1 max-w-md text-sm leading-6 text-white/70">{t("appsHeadlineSub").replace("{agent}", actions.agent)}</p>
        <div className="relative mt-5 flex flex-wrap items-center justify-between gap-3">
          <button onClick={() => actions.onBuild()} className="inline-flex cursor-pointer items-center gap-2 rounded-full bg-white px-4 py-2 text-sm font-semibold text-black transition hover:bg-white/90">
            <GlowStar size={16} />{t("appsBuild").replace("{agent}", actions.agent)}
          </button>
          <span aria-hidden dir="ltr" className="flex gap-1"><Star size={10} /><Star size={10} /><Star size={10} hollow /></span>
        </div>
      </div>
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <div className="relative min-w-48 flex-1">
          <Icon name="search" className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <input value={query} onChange={(e) => { setQuery(e.target.value); setView("apps"); }} placeholder={t("appsSearch")} dir="auto"
            className="w-full rounded-xl border border-border bg-background py-2 pe-3 ps-9 text-sm outline-none placeholder:text-muted-foreground focus:border-foreground/30" />
        </div>
        <div className="flex shrink-0 rounded-full border border-border bg-secondary p-0.5" role="tablist">
          {(["apps", "look"] as const).map((k) => (
            <button key={k} role="tab" aria-selected={view === k} onClick={() => setView(k)}
              className={cn("cursor-pointer rounded-full px-3.5 py-1 text-xs transition-colors", view === k ? "bg-background font-medium text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}>
              {t(k === "apps" ? "apps" : "appsLook")}
            </button>
          ))}
        </div>
      </div>
      {view === "look" ? <LookView look={look} admin={catalog.admin} onLook={onLook} /> : (
        <>
          {cats.length > 1 && (
            <div className="mb-6 flex flex-wrap gap-1">
              {[null, ...cats].map((k) => (
                <button key={k?.en ?? ""} onClick={() => setCat(k?.en ?? null)} className={chip(cat === (k?.en ?? null))}>{k ? say(k) : t("all")}</button>
              ))}
            </div>
          )}
          {shown.length === 0 ? (
            <div className="flex flex-col items-center gap-3 py-16 text-center">
              <p className="text-sm text-muted-foreground">{t("appsNone")}</p>
              <button onClick={() => actions.onBuild(query.trim())} className={cn(SOLID, "gap-2 px-4 py-2 text-sm")}>
                <GlowStar size={15} />{t("appsBuildIt").replace("{agent}", actions.agent)}
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {shown.map((a) => <Card key={a.slug} a={a} admin={catalog.admin} actions={actions} onOpen={onOpen} onRemove={onRemove} />)}
            </div>
          )}
        </>
      )}
    </>
  );
}

function Card({ a, admin, actions, onOpen, onRemove }: {
  a: Offered; admin: boolean; actions: StoreActions; onOpen: (a: Offered) => void; onRemove: (a: Offered) => void;
}) {
  const here = a.state === "installed" || a.state === "update" || a.state === "changed";
  const slot = (cls: string, icon: "check" | "refresh" | "plus", title: string) => (
    <span title={title} className={cn("flex size-7 shrink-0 items-center justify-center rounded-full", cls)}><Icon name={icon} className="size-3.5" strokeWidth={2.5} /></span>
  );
  let note: ReactNode = null;
  if (a.state === "update") note = <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[11px] font-medium text-amber-700 dark:text-amber-400">{t("appUpdateAvailable")}</span>;
  if (a.state === "changed") note = <span className="text-[11px] text-muted-foreground">{t("appChanged")}</span>;
  if (a.state === "taken") note = <span className="text-[11px] text-muted-foreground">{t("appTaken")}</span>;
  return (
    <div className="group flex flex-col gap-3 rounded-2xl border border-border bg-background/40 p-4 text-start">
      <button onClick={() => (here ? onOpen(a) : actions.onPeek(a))} className="block cursor-pointer" aria-label={say(a.title)}><Picture src={a.picture} /></button>
      <div className="flex items-center gap-3">
        <AppTile app={face(a)} className="size-10" textClassName="text-base" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-foreground"><bdi>{say(a.title)}</bdi></p>
          <p className="truncate text-[11px] text-muted-foreground"><bdi>{say(a.category)}</bdi></p>
        </div>
        {a.state === "update" ? slot("bg-amber-500/15 text-amber-600", "refresh", t("appUpdateAvailable"))
          : here ? slot("bg-green-500/15 text-green-600", "check", t("appInstalled"))
          : a.state === "available" && slot("border border-border text-muted-foreground", "plus", t("appInstall"))}
      </div>
      {say(a.description) && <p className="line-clamp-2 text-xs leading-relaxed text-muted-foreground"><bdi>{say(a.description)}</bdi></p>}
      <div className="mt-auto flex flex-wrap items-center gap-2">
        {note}
        <span className="ms-auto flex gap-2">
          {here ? (
            <>
              <button onClick={() => onOpen(a)} className={LINE}>{t("open")}</button>
              {admin && <button onClick={() => onRemove(a)} className={LINE}>{t("remove")}</button>}
              {admin && a.state === "update" && install(a, actions)}
            </>
          ) : a.state === "available" && (
            <>
              <button onClick={() => actions.onPeek(a)} className={LINE}>{t("preview")}</button>
              {admin && install(a, actions)}
            </>
          )}
        </span>
      </div>
    </div>
  );
}

// What an app will look like: a small invoice in the look's tokens, as an app built on them reads them.
function Sample({ tokens, label }: { tokens: Tokens; label: string }) {
  const v = (k: string) => `var(${k})`, r = (m = 1) => `calc(var(--radius) * ${m})`;
  return (
    <div style={{ ...(tokens as CSSProperties), background: v("--background"), color: v("--foreground"), borderRadius: r(1.6) }} className="border border-border p-3">
      <p className="mb-2 text-[11px] opacity-60">{label}</p>
      <div style={{ background: v("--card"), border: `1px solid ${v("--border")}`, borderRadius: r(1.4) }} className="p-3">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-sm font-semibold">{t("lookInvoice")} #1042</span>
          <span style={{ background: v("--secondary"), borderRadius: r(0.8) }} className="px-2 py-0.5 text-[11px]">{t("lookDue")}</span>
        </div>
        {[["Al Noor Trading", "12,400"], ["Riyadh Logistics", "8,950"]].map(([who, amt]) => (
          <div key={who} style={{ borderTop: `1px solid ${v("--border")}` }} className="flex justify-between py-1.5 text-xs"><span>{who}</span><span className="tabular-nums">{amt}</span></div>
        ))}
        <div className="mt-2 flex gap-2">
          <span style={{ background: v("--primary"), color: v("--primary-foreground"), borderRadius: r() }} className="px-3 py-1.5 text-xs font-medium">{t("lookPay")}</span>
          <span style={{ border: `1px solid ${v("--input")}`, borderRadius: r() }} className="px-3 py-1.5 text-xs">{t("cancel")}</span>
        </div>
      </div>
    </div>
  );
}

// A small app in a look: a title, two lines and a button.
function Mini({ tokens }: { tokens: Tokens }) {
  const v = (k: string) => `var(${k})`, r = (m = 1) => `calc(var(--radius) * ${m})`;
  return (
    <span style={{ ...(tokens as CSSProperties), background: v("--muted"), borderRadius: r(1.3) }} className="block p-2.5">
      <span style={{ background: v("--card"), border: `1px solid ${v("--border")}`, borderRadius: r() }} className="block space-y-1.5 p-2.5">
        <span className="flex items-center justify-between">
          <span className="h-1.5 w-12 rounded-full" style={{ background: v("--foreground") }} />
          <span className="h-3 w-7" style={{ background: v("--secondary"), borderRadius: r(0.6) }} />
        </span>
        <span className="block h-1 w-full rounded-full" style={{ background: v("--border") }} />
        <span className="block h-1 w-3/4 rounded-full" style={{ background: v("--border") }} />
        <span className="!mt-2.5 block h-4 w-14" style={{ background: v("--primary"), borderRadius: r(0.8) }} />
      </span>
    </span>
  );
}

const LOOK_NAMES: Record<string, Parameters<typeof t>[0]> = { classic: "lookClassic", ocean: "lookOcean", palm: "lookPalm", sand: "lookSand", rose: "lookRose" };

// For people who never heard of a theme: a few ready looks, each seen on a small app, and the company's own colour.
function LookView({ look, admin, onLook }: { look: Look | null; admin: boolean; onLook: (look: Look) => Promise<void> }) {
  const [pick, setPick] = useState<Look>(look ?? { look: "classic" });
  const [color, setColor] = useState(look?.color ?? "#3171f6");
  const chosen = pick.look === "custom" ? { look: "custom", color } : pick;
  const tokens = lookTokens(chosen)!;
  const card = (on: boolean) => cn("relative block rounded-2xl border p-2 text-start transition", admin && "cursor-pointer",
    on ? "border-foreground ring-1 ring-foreground" : "border-border hover:border-foreground/40");
  const tick = <span className="absolute end-3.5 top-3.5 flex size-5 items-center justify-center rounded-full bg-foreground text-background"><Icon name="check" className="size-3" strokeWidth={3} /></span>;
  return (
    <div>
      <p className="mb-5 text-sm text-muted-foreground">{t("lookSub")}</p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {Object.keys(LOOKS).map((id) => (
          <button key={id} disabled={!admin} onClick={() => setPick({ look: id })} className={card(pick.look === id)}>
            <Mini tokens={lookTokens({ look: id })!.light} />
            <span className="mt-2 block px-1 pb-0.5 text-sm font-medium text-foreground">{t(LOOK_NAMES[id])}</span>
            {pick.look === id && tick}
          </button>
        ))}
        <label className={card(pick.look === "custom")}>
          <Mini tokens={lookTokens({ look: "custom", color })!.light} />
          <span className="mt-2 flex items-center gap-2 px-1 pb-0.5 text-sm font-medium text-foreground">
            <span className="size-4 rounded-full border border-black/10" style={{ background: color }} />{t("lookCustom")}
          </span>
          {pick.look === "custom" && tick}
          {admin && <input type="color" value={color} aria-label={t("lookCustom")} onClick={() => setPick({ look: "custom" })}
            onChange={(e) => { setColor(e.target.value); setPick({ look: "custom" }); }} className="absolute inset-0 size-full cursor-pointer opacity-0" />}
        </label>
      </div>
      <p className="mb-2 mt-6 text-xs font-medium text-muted-foreground">{t("lookWill")}</p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Sample tokens={tokens.light} label={t("light")} />
        <Sample tokens={tokens.dark} label={t("dark")} />
      </div>
      {admin && <div className="mt-6 flex justify-end"><button onClick={() => void onLook(chosen)} className={SOLID}>{t("lookUse")}</button></div>}
    </div>
  );
}
