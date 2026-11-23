// Push notifications as plugins (docs/notes/engagement.md). The SDK owns the
// permission prompt and the subscription handshake; who gets pushed, and when,
// is the platform's job. Providers come from Web().notifications(...).
import { getLang } from "./i18n";

export type PushSpec = { provider: string } & Record<string, unknown>;
export type PushStatus = "unsupported" | "default" | "granted" | "denied";
type Api = (path: string, init?: RequestInit & { silent?: boolean; json?: unknown }) => Promise<Response>;

type PushProvider = {
  name: string;
  /** Ask the browser through the vendor SDK, so the push token lands with them. */
  request(): Promise<PushStatus>;
  /** Attach the signed-in user, so the platform can target by id. */
  identify(id: string): void;
  reset(): void;
  /** The app can talk to its server: a browser that already said yes hands its subscription over. */
  ready?(): void;
};

let api: Api | null = null;
const keyBytes = (b64: string) =>
  Uint8Array.from(atob(b64.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (b64.length % 4)) % 4)), (c) => c.charCodeAt(0));

const ONESIGNAL_SDK = "https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.page.js";
// Served by the agent itself (server.py) — a service worker must come from the
// site's own origin; scoped under /push/ so it never intercepts the page.
const ONESIGNAL_WORKER = "push/onesignal/OneSignalSDKWorker.js";

const PLUGINS: Record<string, (spec: PushSpec) => PushProvider | null> = {
  // Our own Web Push (docs/rfc-notifications.md, Devices): the app's worker, subscribed with the server's public key,
  // the subscription handed to the server, which pushes to it itself. No vendor script.
  webpush: (spec) => {
    const key = typeof spec.key === "string" ? spec.key : "";
    if (!key || typeof navigator === "undefined" || !("serviceWorker" in navigator) || !("PushManager" in window)) return null;
    const subscribe = async () => {
      if (pushStatus() !== "granted" || !api) return;
      const reg = await navigator.serviceWorker.register("/push/sw.js", { scope: "/push/" });
      const ours = keyBytes(key);
      let sub = await reg.pushManager.getSubscription();
      const theirs = sub?.options.applicationServerKey;
      if (sub && !(theirs && new Uint8Array(theirs).every((b, i) => b === ours[i]))) { await sub.unsubscribe(); sub = null; }   // a new key
      sub ??= await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: ours });
      await api("/devices", { method: "POST", json: { ...sub.toJSON(), lang: getLang() }, silent: true });
    };
    return {
      name: "webpush",
      async request() {
        await Notification.requestPermission();
        await subscribe().catch(() => {});
        return pushStatus();
      },
      identify() { void subscribe().catch(() => {}); },
      reset() {
        void navigator.serviceWorker.getRegistration("/push/").then((r) => r?.pushManager.getSubscription())
          .then((s) => s?.unsubscribe()).catch(() => {});
      },
      ready() { void subscribe().catch(() => {}); },
    };
  },
  onesignal: (spec) => {
    // Loaded lazily: nothing from the vendor ships until a subscription is
    // wanted — on Allow, or on load for a user who already granted it.
    let sdk: Promise<any> | null = null;
    const load = () => {
      if (sdk) return sdk;
      sdk = new Promise((resolve, reject) => {
        const w = window as any;
        (w.OneSignalDeferred = w.OneSignalDeferred || []).push(async (OneSignal: any) => {
          try {
            await OneSignal.init({
              appId: spec.app_id,
              serviceWorkerParam: { scope: "/push/onesignal/" },
              serviceWorkerPath: ONESIGNAL_WORKER,
            });
            // One sound at a time: while the app is in view the bell sounds, so the push stays hidden.
            OneSignal.Notifications.addEventListener?.("foregroundWillDisplay", (e: any) => {
              if (document.visibilityState === "visible") e?.preventDefault?.();
            });
            resolve(OneSignal);
          } catch (e) { reject(e); }
        });
        if (!document.querySelector(`script[src="${ONESIGNAL_SDK}"]`)) {
          const el = document.createElement("script");
          el.src = ONESIGNAL_SDK; el.defer = true;
          el.onerror = () => reject(new Error("OneSignal SDK failed to load"));
          document.head.appendChild(el);
        }
        setTimeout(() => reject(new Error("OneSignal SDK timed out")), 10000);
      });
      return sdk;
    };
    let userId: string | null = null;
    return {
      name: "onesignal",
      async request() {
        try {
          const OneSignal = await load();
          await OneSignal.Notifications.requestPermission();
          if (userId) OneSignal.login(userId).catch(() => {});
        } catch {
          // The vendor didn't come up; the browser's own prompt still records the answer.
          if ("Notification" in window) await Notification.requestPermission();
        }
        return pushStatus();
      },
      identify(id) {
        userId = id;
        if (pushStatus() === "granted") load().then((o) => o.login(id)).catch(() => {});
      },
      reset() {
        userId = null;
        sdk?.then((o) => o.logout()).catch(() => {});
      },
    };
  },
};

let provider: PushProvider | null = null;

export function initNotifications(specs?: PushSpec[] | null) {
  if (provider) return;
  for (const s of specs || []) {
    const p = PLUGINS[s.provider]?.(s);
    if (p) { provider = p; return; }
  }
}

export function _resetPush() {   // tests only
  provider = null;
}

export const pushProvider = () => provider;

export function pushStatus(): PushStatus {
  if (typeof window === "undefined" || !("Notification" in window)) return "unsupported";
  return Notification.permission;
}

export const requestPush = (): Promise<PushStatus> =>
  provider ? provider.request() : Promise.resolve(pushStatus());
export const identifyPush = (id: string) => provider?.identify(id);
export const resetPush = () => provider?.reset();
/** How the provider reaches the app's own server (the signed-in `api`). */
export function setPushApi(fn: Api | null) {
  api = fn;
  if (fn) provider?.ready?.();
}

// A moment that earns the question: a routine just set up, a first mention. Each asks once on this device, and only
// while the browser hasn't been asked; the card shows its own words for it.
export function askPush(why: "routine" | "mention") {
  if (!provider || pushStatus() !== "default") return;
  try {
    if (localStorage.getItem(`cycls_ask_${why}`)) return;
    localStorage.setItem(`cycls_ask_${why}`, "1");
  } catch { /* private mode: ask anyway */ }
  window.dispatchEvent(new CustomEvent("cycls:ask-push", { detail: why }));
}

/** What the browser said, as the event vocabulary: allowed / denied / dismissed. */
export const answerResult = (s: PushStatus) =>
  s === "granted" ? "allowed" : s === "denied" ? "denied" : "dismissed";

// "Not now" rests the prompt; the flag payload can shorten or lengthen the
// rest (snooze_days), 0 meaning ask again next time.
const SNOOZE_KEY = "cycls_notify_snooze";
export const SNOOZE_DAYS = 14;

export function promptSnoozed(days: number = SNOOZE_DAYS) {
  try {
    const at = Number(localStorage.getItem(SNOOZE_KEY));
    return !!at && Date.now() - at < days * 864e5;
  } catch { return false; }
}

export function snoozePrompt() {
  try { localStorage.setItem(SNOOZE_KEY, String(Date.now())); } catch { /* private mode */ }
}
