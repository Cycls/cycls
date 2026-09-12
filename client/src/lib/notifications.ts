// Push notifications as plugins (docs/notes/engagement.md). The SDK owns the
// permission prompt and the subscription handshake; who gets pushed, and when,
// is the platform's job. Providers come from Web().notifications(...).
export type PushSpec = { provider: string } & Record<string, unknown>;
export type PushStatus = "unsupported" | "default" | "granted" | "denied";

type PushProvider = {
  name: string;
  /** Ask the browser through the vendor SDK, so the push token lands with them. */
  request(): Promise<PushStatus>;
  /** Attach the signed-in user, so the platform can target by id. */
  identify(id: string): void;
  reset(): void;
};

const ONESIGNAL_SDK = "https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.page.js";
// Served by the agent itself (server.py) — a service worker must come from the
// site's own origin; scoped under /push/ so it never intercepts the page.
const ONESIGNAL_WORKER = "push/onesignal/OneSignalSDKWorker.js";

const PLUGINS: Record<string, (spec: PushSpec) => PushProvider | null> = {
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
