/**
 * What a failure tells the person: our words, in their language, and a reference — never the error's own
 * text, which goes to analytics under that reference (src/lib/errors.ts).
 */
import { describe, test, expect, vi, beforeEach } from "vitest";
import { accountError, calloutText, failure } from "../src/lib/errors";
import { track } from "../src/lib/analytics";
import { setLang } from "../src/lib/i18n";

vi.mock("../src/lib/analytics", () => ({ track: vi.fn() }));

const clerk = (code: string, longMessage = "Clerk wording") => ({ errors: [{ code, message: "msg", longMessage }] });

beforeEach(() => { vi.mocked(track).mockClear(); setLang("en"); });

describe("account errors", () => {
  test("one a person can fix reads in our words, and is not tracked as a failure", () => {
    expect(accountError(clerk("form_password_incorrect"), "sign_in")).toBe("That password isn't right.");
    expect(accountError(clerk("too_many_requests"), "sign_in")).toBe("Too many tries. Wait a few minutes and try again.");
    expect(track).not.toHaveBeenCalled();
  });

  test("and in the reader's language", () => {
    setLang("ar");
    expect(accountError(clerk("form_identifier_exists"), "sign_up")).toBe("هذا البريد مسجّل بالفعل، سجّل الدخول بدلًا من ذلك");
  });

  test("any other is a reference, its code and wording kept for us", () => {
    const shown = accountError(clerk("session_reverification_required", "Clerk: verify again"), "settings");
    expect(shown).toMatch(/^Something went wrong\. Reference: [0-9a-f]{8}$/);
    expect(shown).not.toContain("Clerk");
    expect(track).toHaveBeenCalledWith("account_failed", expect.objectContaining({
      error_id: shown.slice(-8), where: "settings", code: "session_reverification_required", detail: "Clerk: verify again" }));
  });
});

test("a failure reads as one sentence in each language", () => {
  setLang("ar");
  expect(failure("message_failed", new Error("x"))).toMatch(/^حدث خطأ ما \(المرجع: [0-9a-f]{8}\)$/);
});

test("a failure keeps the error's text off the screen and in analytics", () => {
  const shown = failure("message_failed", new Error('Clerk: Network request failed while offline. (code="clerk_offline")'));
  expect(shown).not.toMatch(/Clerk|clerk_offline/);
  expect(track).toHaveBeenCalledWith("message_failed", expect.objectContaining({
    error_id: shown.slice(-8), error_message: expect.stringContaining("clerk_offline") }));
});

describe("a callout the server names by code reads in the reader's language", () => {
  test("busy, with its reference; declined; and a failure by its reference alone", () => {
    expect(calloutText({ code: "busy", error_id: "ab12cd34", callout: "The service is busy right now…" }))
      .toBe("The service is busy right now. Try again in a minute. Reference: ab12cd34");
    setLang("ar");
    expect(calloutText({ code: "busy", error_id: "ab12cd34" })).toBe("الخدمة مشغولة الآن، حاول مجددًا بعد دقيقة (المرجع: ab12cd34)");
    expect(calloutText({ code: "declined" })).toBe("تعذّرت الإجابة عن هذا الطلب، جرّب صياغته بطريقة أخرى");
    expect(calloutText({ style: "error", error_id: "ab12cd34", callout: "Something went wrong. Reference: `ab12cd34`" }))
      .toBe("حدث خطأ ما (المرجع: ab12cd34)");
  });

  test("any other stays as the server said it", () => {
    expect(calloutText({ style: "warning", callout: "This chat is already working on a reply." }))
      .toBe("This chat is already working on a reply.");
  });
});
