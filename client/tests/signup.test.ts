import { describe, it, expect, vi, beforeEach } from "vitest";
import { markSignup, detectSignup, startSignup, needsPhone, toE164, latinDigits, PHONE_COUNTRIES } from "../src/lib/signup";

const track = vi.fn();
vi.mock("../src/lib/analytics", () => ({ track: (...a: unknown[]) => track(...a) }));

const fresh = () => new Date(Date.now() - 30_000);
const old = () => new Date(Date.now() - 86_400_000);

describe("sign_up, once per account", () => {
  beforeEach(() => { track.mockClear(); localStorage.clear(); sessionStorage.clear(); });

  it("counts a second account registered in the same browser", () => {
    markSignup("password", "user_a");
    markSignup("password", "user_b");
    expect(track).toHaveBeenCalledTimes(2);
  });

  it("never counts the same account twice", () => {
    markSignup("email_code", "user_a");
    markSignup("email_code", "user_a");
    detectSignup({ id: "user_a", createdAt: fresh() });
    expect(track).toHaveBeenCalledTimes(1);
  });

  it("a tester's own sign-in does not silence the next registration", () => {
    detectSignup({ id: "tester", createdAt: old() });        // existing account, nothing to count
    expect(track).not.toHaveBeenCalled();
    detectSignup({ id: "new_via_google", createdAt: fresh() });
    expect(track).toHaveBeenCalledWith("sign_up", { method: "oauth" });
  });

  it("a form that fired before knowing the id is not counted again on load", () => {
    markSignup("password", null);
    detectSignup({ id: "user_c", createdAt: fresh() });
    expect(track).toHaveBeenCalledTimes(1);
    expect(track).toHaveBeenCalledWith("sign_up", { method: "password" });
  });

  it("the old per-browser flag does not block anyone", () => {
    localStorage.setItem("cycls_signup_tracked", "1");
    detectSignup({ id: "user_d", createdAt: fresh() });
    expect(track).toHaveBeenCalledTimes(1);
  });
});


describe("sign_up_start and the OAuth method", () => {
  beforeEach(() => { track.mockClear(); localStorage.clear(); sessionStorage.clear(); });

  it("starts once per visit, whichever surface comes first", () => {
    startSignup({ source: "compose", has_draft: true });
    startSignup({ source: "auth_screen" });
    expect(track).toHaveBeenCalledTimes(1);
    expect(track).toHaveBeenCalledWith("sign_up_start", { source: "compose", has_draft: true });
  });

  it("names the OAuth provider as the method", () => {
    detectSignup({ id: "u", createdAt: fresh() }, "google");
    expect(track).toHaveBeenCalledWith("sign_up", { method: "google" });
  });
});

describe("the phone step, only when Clerk waits on the phone alone", () => {
  const su = (missingFields: string[], unverifiedFields: string[] = [], status = "missing_requirements") =>
    ({ status, missingFields, unverifiedFields });

  it("opens once the email or Google/Apple account is done and the number is all that's left", () => {
    expect(needsPhone(su(["phone_number"]))).toBe(true);             // Google, Apple, or email verified
    expect(needsPhone(su([], ["phone_number"]))).toBe(true);         // number given, code not yet entered
  });

  it("stays closed while the email still needs its code, or Clerk wants something else too", () => {
    expect(needsPhone(su(["phone_number"], ["email_address"]))).toBe(false);
    expect(needsPhone(su(["phone_number", "first_name"]))).toBe(false);
  });

  it("writes the number the way Clerk wants it, without the 0 people type at home", () => {
    expect(toE164("966", "0551234567")).toBe("+966551234567");
    expect(toE164("966", "55 123 4567")).toBe("+966551234567");
    expect(toE164("971", "050-123-4567")).toBe("+971501234567");
    expect(toE164("966", "+966 55 123 4567")).toBe("+966551234567");   // pasted whole, the picker aside
    expect(toE164("966", "00971501234567")).toBe("+971501234567");
  });

  it("offers every country, each once, with its dialing code", () => {
    const regions = PHONE_COUNTRIES.map(([r]) => r);
    expect(regions.length).toBeGreaterThan(200);
    expect(new Set(regions).size).toBe(regions.length);
    expect(Object.fromEntries(PHONE_COUNTRIES)).toMatchObject({ SA: "966", AE: "971", EG: "20", US: "1", CA: "1", GB: "44" });
  });

  it("reads the digits an Arabic keyboard types, in a number and in a code", () => {
    expect(toE164("966", "٠٥٥ ١٢٣ ٤٥٦٧")).toBe("+966551234567");
    expect(toE164("966", "۰۵۵۱۲۳۴۵۶۷")).toBe("+966551234567");   // the Persian forms some layouts type
    expect(latinDigits("٤٢٤٢٤٢")).toBe("424242");
    expect(latinDigits("12٣4")).toBe("1234");
  });

  it("never opens with Clerk's phone requirement off: the sign-up completes, or waits on other things", () => {
    expect(needsPhone(su([], [], "complete"))).toBe(false);
    expect(needsPhone(su([], ["email_address"]))).toBe(false);
    expect(needsPhone(null)).toBe(false);
  });
});
