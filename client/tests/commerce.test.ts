import { describe, it, expect } from "vitest";
import { commerceProps, onFreePlan } from "../src/lib/commerce";

const pro = { id: "plan_pro", name: "Pro", hasBaseFee: true,
              fee: { amount: 2000, currency: "USD" }, annualFee: { amount: 19200, currency: "USD" } };
const free = { id: "plan_free", name: "Free", hasBaseFee: false, fee: { amount: 0, currency: "USD" }, annualFee: null };

describe("commerce props", () => {
  it("values the period that is charged, in major units, in Clerk's currency", () => {
    expect(commerceProps(pro, "month", "user")).toMatchObject({ value: 20, currency: "USD", billing_period: "month", is_free: false });
    expect(commerceProps(pro, "annual", "user").value).toBe(192);   // the annual total, not the monthly equivalent
  });

  it("marks a free plan and never invents a previous plan", () => {
    const p = commerceProps(free, "month", "organization", "Free");
    expect(p).toMatchObject({ value: 0, is_free: true, payer_type: "organization" });
    expect(p).not.toHaveProperty("previous_plan");
  });

  it("names the plan being left when switching", () => {
    expect(commerceProps(pro, "month", "user", "Free").previous_plan).toBe("Free");
  });
});

describe("the top bar's Subscribe", () => {
  it("is for a payer billing knows, with no live plan that has a fee", () => {
    const item = (hasBaseFee: boolean, status = "active") => ({ status, plan: { hasBaseFee } });
    expect(onFreePlan({ subscriptionItems: [item(false)] })).toBe(true);
    expect(onFreePlan({ subscriptionItems: [item(true)] })).toBe(false);
    expect(onFreePlan({ subscriptionItems: [item(true, "past_due")] })).toBe(false);   // still theirs while it's settled
    expect(onFreePlan({ subscriptionItems: [item(true, "ended"), item(false)] })).toBe(true);   // a paid plan that ran out
    expect(onFreePlan({ subscriptionItems: [item(false), item(true, "upcoming")] })).toBe(true);
    expect(onFreePlan(null)).toBe(false);   // billing off, or not known yet: no button
  });
});
