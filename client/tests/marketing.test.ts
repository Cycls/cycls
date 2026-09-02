/**
 * The analytics bus: one pipe of canonical events, providers as plugins,
 * per-provider allowlist routing. Tested through the gtm plugin (posthog's
 * would boot the real SDK).
 */
import { describe, it, expect, beforeEach } from "vitest";
import { initAnalytics, track, register, _resetProviders } from "../src/lib/posthog";

type W = { dataLayer?: unknown[] };
const w = window as unknown as W;

describe("analytics bus", () => {
  beforeEach(() => {
    _resetProviders();
    w.dataLayer = [];
  });

  it("routes only allowlisted events to a scoped provider", () => {
    initAnalytics([{ provider: "gtm", events: ["sign_up", "purchase"] }]);
    track("sign_up", { method: "oauth" });
    track("artifact_completed", { kind: "html" });
    expect(w.dataLayer).toEqual([{ event: "sign_up", method: "oauth" }]);
  });

  it("an unscoped provider receives everything, names verbatim", () => {
    initAnalytics([{ provider: "gtm" }]);
    track("checkout_start", { value: 20, currency: "USD" });
    expect(w.dataLayer).toEqual([{ event: "checkout_start", value: 20, currency: "USD" }]);
  });

  it("bus super-props are stamped for providers without native register", () => {
    initAnalytics([{ provider: "gtm" }]);
    register({ agent_name: "super" });
    track("purchase", { value: 20 });
    expect(w.dataLayer).toEqual([{ event: "purchase", agent_name: "super", value: 20 }]);
  });

  it("no providers configured → the pipe is inert", () => {
    track("sign_up", {});
    expect(w.dataLayer).toEqual([]);
  });

  it("unknown provider specs are skipped, duplicates ignored", () => {
    initAnalytics([{ provider: "nope" }, { provider: "gtm" }, { provider: "gtm" }]);
    track("sign_up", {});
    expect(w.dataLayer).toEqual([{ event: "sign_up" }]);
  });
});
