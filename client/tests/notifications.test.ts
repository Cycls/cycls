import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { initNotifications, pushProvider, pushStatus, promptSnoozed, snoozePrompt, answerResult, _resetPush, requestPush, setPushApi, askPush } from "../src/lib/notifications";

describe("push providers are plugins", () => {
  beforeEach(() => { _resetPush(); localStorage.clear(); });

  it("picks the configured provider", () => {
    initNotifications([{ provider: "carrier-pigeon" }, { provider: "onesignal", app_id: "x" }]);
    expect(pushProvider()?.name).toBe("onesignal");
  });

  it("reads a browser without a Notification API as unsupported", () => {
    expect(pushStatus()).toBe("unsupported");
    expect(answerResult("granted")).toBe("allowed");
    expect(answerResult("default")).toBe("dismissed");
  });

  it("snoozes for the given days, and 0 means ask again", () => {
    expect(promptSnoozed()).toBe(false);
    snoozePrompt();
    expect(promptSnoozed()).toBe(true);
    expect(promptSnoozed(0)).toBe(false);
  });
});

describe("our own Web Push", () => {
  const KEY = "BP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8";
  const browser = (permission = "default") => {
    const sub = { options: { applicationServerKey: null }, unsubscribe: vi.fn(),
                  toJSON: () => ({ endpoint: "https://push.example/1", keys: { p256dh: "p", auth: "a" } }) };
    const pushManager = { getSubscription: vi.fn(async () => null), subscribe: vi.fn(async () => sub) };
    const N = { permission, requestPermission: vi.fn(async () => { N.permission = "granted"; return "granted"; }) };
    vi.stubGlobal("Notification", N);
    vi.stubGlobal("PushManager", function PushManager() {});
    Object.defineProperty(navigator, "serviceWorker", { configurable: true, value: { register: vi.fn(async () => ({ pushManager })) } });
    return pushManager;
  };
  beforeEach(() => { _resetPush(); setPushApi(null); localStorage.clear(); });
  afterEach(() => { vi.unstubAllGlobals(); delete (navigator as { serviceWorker?: unknown }).serviceWorker; });

  it("comes before a vendor, subscribes the app's worker with the server's key, and hands the subscription over", async () => {
    const pushManager = browser();
    const api = vi.fn(async () => new Response("{}"));
    initNotifications([{ provider: "webpush", key: KEY }, { provider: "onesignal", app_id: "x" }]);
    expect(pushProvider()?.name).toBe("webpush");
    setPushApi(api);
    expect(api).not.toHaveBeenCalled();   // not before the person says yes
    expect(await requestPush()).toBe("granted");
    expect(navigator.serviceWorker.register).toHaveBeenCalledWith("/push/sw.js", { scope: "/push/" });
    expect(pushManager.subscribe).toHaveBeenCalledWith({ userVisibleOnly: true, applicationServerKey: expect.any(Uint8Array) });
    expect(api).toHaveBeenCalledWith("/devices", { method: "POST", silent: true,
      json: { endpoint: "https://push.example/1", keys: { p256dh: "p", auth: "a" }, lang: "en" } });
  });

  it("without the server's key a vendor takes over, and a moment asks once on this device", () => {
    browser();
    initNotifications([{ provider: "webpush" }, { provider: "onesignal", app_id: "x" }]);
    expect(pushProvider()?.name).toBe("onesignal");
    const asked: string[] = [];
    const on = (e: Event) => asked.push((e as CustomEvent).detail);
    window.addEventListener("cycls:ask-push", on);
    askPush("routine"); askPush("routine"); askPush("mention");
    window.removeEventListener("cycls:ask-push", on);
    expect(asked).toEqual(["routine", "mention"]);
  });
});
