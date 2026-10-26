// Scenes for the screenshots: the real components from client/src, the API mocked in memory.
//   ?scene=menu | catalog | theme | app      &lang=ar  &dark=1  &admin=0  &palette=<color>|<base>-<color>
import { StrictMode, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./harness.css";
import { InputBox, type MenuApp } from "../../client/src/components/input-box";
import { ConnectorsDialog, type Connector } from "../../client/src/components/connectors-dialog";
import { CanvasDoc } from "../../client/src/components/canvas";
import { ToastProvider } from "../../client/src/lib/toast";
import { setLang } from "../../client/src/lib/i18n";
import { setAppTheme, type AppThemeChoice, type Base, type Color } from "../../client/src/lib/app-theme";
import catalogRows from "./catalog.json";

const q = new URLSearchParams(location.search);
const scene = q.get("scene") ?? "catalog";
if (q.get("lang") === "ar") setLang("ar");
if (q.get("dark") === "1") document.body.classList.add("dark");
const admin = q.get("admin") !== "0";

// What the workspace has: three installed, one behind the image, one a person's own app of that name.
const state: Record<string, string> = { tasks: "installed", minutes: "installed", calendar: "installed", kpi: "update", forms: "conflict" };
let theme: AppThemeChoice | null = null;

function parsePalette(p: string | null): AppThemeChoice | null {
  if (!p) return null;
  const [a, b] = p.includes("-") ? p.split("-") : ["neutral", p];
  return { base: a as Base, color: b as Color, radius: Number(q.get("radius") ?? 0.625) };
}

const api = (async (path: string, init: { method?: string; json?: unknown } = {}) => {
  const ok = (b: unknown) => new Response(JSON.stringify(b), { status: 200, headers: { "content-type": "application/json" } });
  const method = init.method ?? "GET";
  await new Promise((r) => setTimeout(r, 60));
  if (path === "/apps/catalog") return ok({ admin, apps: catalogRows.map((r) => ({ ...r, state: state[r.slug] ?? "available" })) });
  if (path === "/apps/theme" && method === "GET") return ok({ theme, default: null, admin });
  if (path === "/apps/theme") { theme = (init.json as { theme: AppThemeChoice | null }).theme; return ok({ ok: true, theme }); }
  if (path === "/apps/install" || path === "/apps/update") { state[(init.json as { slug: string }).slug] = "installed"; return ok({ ok: true }); }
  if (path === "/apps/uninstall") { delete state[(init.json as { slug: string }).slug]; return ok({ ok: true }); }
  if (path === "/skills") return ok({ skills: [], scopes: ["me"], org_admin: false });
  return ok([]);
}) as unknown as Parameters<typeof ConnectorsDialog>[0]["api"];

const svg = (fill: string, letter: string) =>
  `data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="7" fill="${fill}"/><text x="16" y="21.5" font-family="Arial" font-size="15" font-weight="700" fill="#fff" text-anchor="middle">${letter}</text></svg>`)}`;
const connectors = [
  { name: "drive", title: { en: "Google Drive", ar: "جوجل درايف" }, icon: svg("#1a73e8", "D"), connected: true, on: true, allowed: true },
  { name: "salla", title: { en: "Salla", ar: "سلة" }, icon: svg("#0b6b5d", "S"), connected: true, on: false, allowed: true },
] as unknown as Connector[];

function installedApps(): MenuApp[] {
  return catalogRows.filter((r) => state[r.slug] === "installed" || state[r.slug] === "update").map((r) => ({
    slug: r.slug, entry: `apps/${r.slug}/index.html`, icon: r.icon ?? undefined,
    name: (document.documentElement.lang === "ar" && r.name_ar) || r.name || r.slug,
  }));
}

function MenuScene() {
  const ref = useRef<HTMLTextAreaElement>(null);
  const [input, setInput] = useState("");
  return (
    <div className="flex h-dvh flex-col bg-background">
      <div className="flex-1" />
      <div className="mx-auto w-full max-w-3xl px-4 pb-6">
        <InputBox textareaRef={ref} input={input} setInput={setInput} handleKeyDown={() => {}} handleSubmit={() => {}}
          isStreaming={false} onStop={() => {}} listening={false} transcribing={false}
          startMic={() => {}} stopMic={() => {}} cancelMic={() => {}}
          onOpenFilePicker={() => {}} onOpenFiles={() => {}} connectors={connectors}
          onOpenConnectors={() => {}} onOpenSkills={() => {}} onToggleConnector={() => {}}
          apps={installedApps()} onOpenApp={() => {}} onBrowseApps={() => {}} />
      </div>
    </div>
  );
}

function DialogScene({ view }: { view: "browse" | "theme" }) {
  return (
    <div className="h-dvh bg-background">
      <ConnectorsDialog api={api} items={connectors} reload={() => {}} initialTab="apps" onClose={() => {}}
        onUsePrompt={() => {}} onAsk={() => {}} apps={{ onOpen: () => {}, view }} />
    </div>
  );
}

function AppScene() {
  const [html, setHtml] = useState<string | null>(null);
  const [label, setLabel] = useState(q.get("palette") ?? "none");
  useEffect(() => { fetch("/tasks.html").then((r) => r.text()).then(setHtml); }, []);
  useEffect(() => {
    // Playwright pushes a new theme live, as the Theme panel's Save does: no reload of the app.
    (window as unknown as { __theme: (p: string | null) => void }).__theme = (p) => { setAppTheme(parsePalette(p)); setLabel(p ?? "none"); };
  }, []);
  const file = useMemo(() => ({ path: "apps/tasks/index.html", name: "Tasks" }), []);
  return (
    <div className="flex h-dvh flex-col bg-background">
      <div className="flex h-10 shrink-0 items-center gap-2 border-b border-border px-4 text-xs text-muted-foreground">
        <span className="font-medium text-foreground">apps/tasks/index.html</span>
        <span>· canvas, real shim + bridge ·</span>
        <span data-palette>{`theme: ${label}`}</span>
      </div>
      <div className="min-h-0 flex-1">
        {/* no readFile/appData: the kit runs in gallery mode with its demo rows */}
        <CanvasDoc file={file} content={html} error={false} shared />
      </div>
    </div>
  );
}

setAppTheme(parsePalette(q.get("palette")));
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ToastProvider>
      {scene === "menu" ? <MenuScene /> : scene === "app" ? <AppScene /> : <DialogScene view={scene === "theme" ? "theme" : "browse"} />}
    </ToastProvider>
  </StrictMode>,
);
