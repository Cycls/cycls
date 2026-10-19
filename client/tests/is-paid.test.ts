// is_paid comes from the token's plan claim, never from a plan's display name.
import { describe, test, expect, afterEach, vi } from "vitest";

const ph = vi.hoisted(() => ({ init: vi.fn(), identify: vi.fn() }));
vi.mock("posthog-js", () => ({ default: ph }));

import { identifyUser, initAnalytics, _resetProviders } from "../src/lib/analytics";

const user = { id: "user_1" };
const sent = (plan?: string | null) => {
  identifyUser(user, { plan });
  return ph.identify.mock.calls.at(-1)?.[1] as Record<string, unknown>;
};

afterEach(() => { _resetProviders(); ph.identify.mockClear(); });

describe("plans", () => {
  test("a personal plan and an org plan are kept apart; free plans are not paid", () => {
    initAnalytics([{ provider: "posthog" }]);
    expect(sent("u:free_user")).toMatchObject({ user_plan: "u:free_user", user_is_paid: false });
    expect(sent("u:pro")).toMatchObject({ user_plan: "u:pro", user_is_paid: true });
    const org = sent("o:team");
    expect(org).toMatchObject({ org_plan: "o:team", org_is_paid: true });
    expect(org).not.toHaveProperty("user_is_paid");      // the personal plan is left as it was
    expect(sent("o:free_org")).toMatchObject({ org_is_paid: false });
    expect(Object.keys(sent(undefined)).filter((k) => k.includes("plan") || k.includes("paid"))).toEqual([]);
  });
});
