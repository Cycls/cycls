import { describe, it, expect } from "vitest";
import { commerceProps } from "../src/lib/commerce";

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
