import { describe, it, expect, beforeEach } from "vitest";
import { initNotifications, pushProvider, pushStatus, promptSnoozed, snoozePrompt, answerResult, _resetPush } from "../src/lib/notifications";

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
