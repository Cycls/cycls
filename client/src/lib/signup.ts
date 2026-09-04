// The sign_up conversion, once per account. A browser can host many accounts
// — a tester signs in with their own, then registers a fresh one — so the
// gate is keyed by account id, never by browser.
import { track } from "./analytics";

const KEY = "cycls_signup_tracked";     // JSON list of account ids already counted
const PENDING = "cycls_signup_pending"; // a form flow fired before the id was known
const FRESH_MS = 5 * 60_000;

function counted(): string[] {
  try { const v = JSON.parse(localStorage.getItem(KEY) || "[]"); return Array.isArray(v) ? v : []; } catch { return []; }
}
function remember(id: string) {
  try { localStorage.setItem(KEY, JSON.stringify([...new Set([...counted(), id])].slice(-50))); } catch { /* private mode */ }
}

/** A password or code flow reached Clerk's "complete": count the new account now. */
export function markSignup(method: string, userId?: string | null) {
  if (userId) {
    if (counted().includes(userId)) return;
    remember(userId);
  } else {
    try { sessionStorage.setItem(PENDING, "1"); } catch { /* private mode */ }
  }
  track("sign_up", { method });
}

/** First authed load: a just-created account nobody has counted is a sign-up —
 *  OAuth has no other moment, the redirect swallows it. */
export function detectSignup(user: { id: string; createdAt?: Date | string | null } | null | undefined) {
  if (!user?.id || !user.createdAt) return;
  if (counted().includes(user.id)) return;
  remember(user.id);
  let pending = false;
  try { pending = sessionStorage.getItem(PENDING) === "1"; sessionStorage.removeItem(PENDING); } catch { /* private mode */ }
  if (pending) return;   // the form already counted this account
  if (Date.now() - new Date(user.createdAt).getTime() < FRESH_MS) track("sign_up", { method: "oauth" });
}
