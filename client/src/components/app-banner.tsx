import { useEffect, useState } from "react";
import { Icon } from "./icon";
import { t } from "../lib/i18n";
import { track } from "../lib/analytics";
import type { AppConfig } from "../hooks/use-chat";

// Phone visitors are pointed to the native app (Web().mobile_app). The browser's own way comes
// first: Safari draws Apple's banner from the meta tag the server adds, and Chrome on Android opens
// Google's install sheet from the manifest. This glass bar, as wide as the composer, is the fallback
// everywhere else, and the button that sheet needs. Dismissing rests it for two weeks, as does Open.
const KEY = "cycls_app_banner";
const REST_DAYS = 14;
let reported = false;   // one `shown` per page load, however many pages mount it

// Chrome only opens the install sheet from a tap, so its event waits here for Open.
type InstallPrompt = Event & { prompt: () => Promise<unknown> };
let installPrompt: InstallPrompt | null = null;
window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); installPrompt = e as InstallPrompt; });

export function platform(ua = navigator.userAgent, touch = navigator.maxTouchPoints): "ios" | "android" | null {
  if (/android/i.test(ua)) return "android";
  if (/iphone|ipad|ipod/i.test(ua) || (/macintosh/i.test(ua) && touch > 1)) return "ios";   // iPadOS asks for the desktop site
  return null;
}

// Safari itself, not Chrome, Firefox, Edge, Opera, the Google app or DuckDuckGo, which say Safari too.
const safari = (ua: string) => /Safari\//.test(ua) && !/CriOS|FxiOS|EdgiOS|OPiOS|OPT\/|GSA\/|Ddg\//.test(ua);

function resting() {
  try {
    const at = Number(localStorage.getItem(KEY));
    return !!at && Date.now() - at < REST_DAYS * 864e5;
  } catch { return false; }
}

export function AppBanner() {
  const os = platform();
  const href = os && !(os === "ios" && safari(navigator.userAgent))
    && (window as { __CONFIG__?: AppConfig }).__CONFIG__?.mobile_app?.[os];
  const [open, setOpen] = useState(() => !!href && !resting());
  useEffect(() => {
    if (open && !reported) { reported = true; track("app_banner_shown", { platform: os }); }
  }, [open, os]);
  if (!open || !href) return null;
  const rest = (event: string, props: Record<string, string> = {}) => {
    track(event, { platform: os, ...props });
    try { localStorage.setItem(KEY, String(Date.now())); } catch { /* private mode */ }
    setOpen(false);
  };
  const openApp = (e: React.MouseEvent) => {
    const sheet = installPrompt;
    if (sheet) { e.preventDefault(); installPrompt = null; sheet.prompt().catch(() => {}); }
    rest("app_banner_clicked", { via: sheet ? "prompt" : "store" });
  };
  return (
    <div className="shrink-0 px-6 pt-1 pb-3" data-testid="app-banner">
      <div className="mx-auto flex w-full max-w-3xl items-center gap-3 rounded-[18px] border border-white/60 bg-background/60 p-2.5 pe-2 shadow-[0_8px_32px_-6px_rgb(0_0_0/0.18),inset_0_1px_0_rgb(255_255_255/0.7)] backdrop-blur-xl backdrop-saturate-150 dark:border-white/10 dark:shadow-[0_8px_32px_-6px_rgb(0_0_0/0.7),inset_0_1px_0_rgb(255_255_255/0.08)]">
        <img src="/app-icon-192.png" alt="" className="size-9 shrink-0 rounded-[8px] ring-1 ring-black/5 dark:ring-white/15" />
        <span className="min-w-0 flex-1 leading-tight">
          <span className="block truncate text-sm font-semibold text-foreground">{t("appBannerTitle")}</span>
          <span className="block truncate text-xs text-muted-foreground">{t("appBannerText")}</span>
        </span>
        <a href={href} target="_blank" rel="noopener" onClick={openApp}
           className="shrink-0 rounded-full border border-black/12 bg-black/5 px-4 py-1.5 text-sm font-semibold text-foreground transition-colors hover:bg-black/10 dark:border-white/14 dark:bg-white/10 dark:hover:bg-white/15">
          {t("appBannerOpen")}
        </a>
        <button onClick={() => rest("app_banner_dismissed")} aria-label={t("dismiss")}
                className="shrink-0 rounded-full p-1.5 text-muted-foreground transition-colors hover:text-foreground cursor-pointer">
          <Icon name="x" className="size-3.5" />
        </button>
      </div>
    </div>
  );
}
