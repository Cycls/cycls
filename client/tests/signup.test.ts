import { describe, it, expect, vi, beforeEach } from "vitest";
import { markSignup, detectSignup } from "../src/lib/signup";

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
