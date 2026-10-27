import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { PricingCards } from "../src/components/pricing-cards";
import { setLang } from "../src/lib/i18n";
import type { Part } from "../src/hooks/use-chat";

// The plans window: opened by a limit it thanks the person, the button leads with the plan on offer already
// chosen, the ways to pay sit under it as their official marks, and plans read in the reader's language.

const usd = (amount: number) => ({ amount, currency: "USD", currencySymbol: "$" });
const PLANS = [
  { id: "p_pro", slug: "pro", name: "Pro", description: "For professionals who use AI daily.", publiclyVisible: true, hasBaseFee: true,
    fee: usd(2000), annualFee: usd(20400), annualMonthlyFee: usd(1700), freeTrialEnabled: false,
    features: [{ id: "f1", slug: "memory", name: "Memory" }] },
  { id: "p_max", slug: "max", name: "Max", description: "For power users who need more.", publiclyVisible: true, hasBaseFee: true,
    fee: usd(10000), annualFee: usd(102000), annualMonthlyFee: usd(8500), freeTrialEnabled: false,
    features: [{ id: "f2", slug: "priority_support", name: "Priority support" }] },
];
vi.mock("@clerk/react", () => ({ Show: ({ children }: { children: unknown }) => children, useUser: () => ({ user: { id: "u1" } }) }));
vi.mock("@clerk/react/experimental", () => ({
  usePlans: () => ({ data: PLANS, isLoading: false }),
  useSubscription: () => ({ data: null }),
  CheckoutButton: ({ children }: { children: unknown }) => children,
  SubscriptionDetailsButton: ({ children }: { children: unknown }) => children,
}));
vi.mock("../src/lib/analytics", () => ({ track: vi.fn() }));

const setup = {
  pay: ["apple_pay", "google_pay", "visa", "mastercard"], currency: ["SAR", 3.75] as [string, number],
  words: { pro: { ar: { name: "برو" } }, memory: { ar: { name: "الذاكرة" } } },
};
const usage: Part = { type: "usage", used: 14, limit: 14, per: "month", resets: "2026-11-01" };

afterEach(() => { cleanup(); setLang("en"); });

describe("the plans window", () => {
  it("opened by the limit, thanks the person, and its button leads with the plan on offer", () => {
    const later = vi.fn();
    render(<PricingCards why="limit" usage={usage} agent="Super" setup={setup} onSelect={() => {}} onLater={later} />);
    expect(screen.getByText("Thanks for trying Super")).toBeTruthy();
    expect(screen.getByText("You've used this month's 14 free messages, and we'd love to keep going with you.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Subscribe and keep going" })).toBeTruthy();
    expect(screen.getByText(/^Pro · \$20 a month · about SAR\s?75 · cancel anytime$/)).toBeTruthy();
    expect(screen.getByRole("radio", { name: /Pro.*Recommended/ }).getAttribute("aria-checked")).toBe("true");
    fireEvent.click(screen.getByText("Not now"));
    expect(later).toHaveBeenCalled();
  });

  it("shows the ways to pay it was given, in order, as their marks", () => {
    render(<PricingCards setup={setup} onSelect={() => {}} />);
    expect(screen.getAllByRole("img").map((i) => i.getAttribute("alt"))).toEqual(["Apple Pay", "Google Pay", "Visa", "Mastercard"]);
    expect(screen.getByText("Secure payment")).toBeTruthy();
  });

  it("follows the plan and period chosen under the button", () => {
    render(<PricingCards setup={setup} onSelect={() => {}} />);
    expect(screen.getByText("Choose your plan")).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: /Max/ }));
    expect(screen.getByRole("button", { name: "Subscribe to Max" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Annual/ }));
    expect(screen.getByText("Save 15%")).toBeTruthy();
    expect(screen.getByText(/^Max · \$1,020 a year · about SAR\s?3,825 · cancel anytime$/)).toBeTruthy();
  });

  it("reads its plans in Arabic from the words it was given, and falls back to the billing provider's", () => {
    setLang("ar");
    render(<PricingCards why="limit" usage={usage} agent="سوبر" setup={setup} onSelect={() => {}} />);
    expect(screen.getByText("شكراً لأنك جرّبت سوبر")).toBeTruthy();
    expect(screen.getByRole("button", { name: "اشترك وكمّل شغلك" })).toBeTruthy();
    expect(screen.getByText("الذاكرة")).toBeTruthy();
    expect(screen.getByRole("radio", { name: /برو/ })).toBeTruthy();
    expect(screen.getByRole("radio", { name: /Max/ })).toBeTruthy();   // no Arabic given: the plan's own name
  });
});
