import { t } from "./i18n";
import { track } from "./analytics";

type Key = Parameters<typeof t>[0];

// A failure as the person sees it: our words and a reference, never the error's own text. That text, a
// vendor's name and codes with it, goes to analytics under the reference, as the server's go to its log.
export function reference(event: string, err: unknown, props: Record<string, unknown> = {}): string {
  const id = crypto.randomUUID().slice(0, 8);
  track(event, { ...props, error_id: id, error_message: String((err as Error)?.message ?? err).slice(0, 300) });
  return id;
}

// The line a failure shows: one sentence per language, so each joins it its own way.
export const failedRef = (id: string) => t("failedRef").replace("{ref}", id);

export const failure = (event: string, err: unknown, props?: Record<string, unknown>) =>
  failedRef(reference(event, err, props));

// A callout's words. One the server or this client names by `code` reads in the reader's language, a failure by
// its reference; any other (a server's own reason, a connector's) as it came.
export function calloutText(p: { callout?: string; code?: string; error_id?: string; style?: string }): string {
  const ref = p.error_id ?? "";
  switch (p.code) {
    case "busy": return t("serviceBusyRef").replace("{ref}", ref);
    case "declined": return t("cantAnswer");
    case "signed_out": return t("signedOut");
    case "too_many": return t("tooManyMessages");
  }
  return ref && p.style === "error" ? failedRef(ref) : p.callout ?? "";
}

// The account errors a person can fix, by Clerk's code, in the reader's language. Any other is a failure.
const ACCOUNT: Record<string, Key> = {
  form_password_incorrect: "authWrongPassword",
  form_identifier_not_found: "authNoAccount",
  form_code_incorrect: "authWrongCode",
  form_identifier_exists: "authEmailTaken",
  form_password_pwned: "authWeakPassword",
  form_password_length_too_short: "authWeakPassword",
  form_password_not_strong_enough: "authWeakPassword",
  strategy_for_user_invalid: "authOtherWay",
  user_locked: "authTooMany",
  too_many_requests: "authTooMany",
};

export function accountError(err: unknown, where: string): string {
  const first = (err as { errors?: { code?: string; longMessage?: string }[] })?.errors?.[0];
  const key = first?.code && ACCOUNT[first.code];
  return key ? t(key) : failure("account_failed", err, { where, code: first?.code, detail: first?.longMessage });
}
