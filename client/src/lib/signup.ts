// The sign_up conversion, once per account. A browser can host many accounts
// — a tester signs in with their own, then registers a fresh one — so the
// gate is keyed by account id, never by browser.
import { track } from "./analytics";

const KEY = "cycls_signup_tracked";     // JSON list of account ids already counted
const PENDING = "cycls_signup_pending"; // a form flow fired before the id was known
const STARTED = "cycls_signup_started"; // sign_up_start, once per visit
const FRESH_MS = 5 * 60_000;

/** The visitor starts to sign up — from the public shell, or the sign-up form
 *  itself. Once per visit, whichever comes first. */
export function startSignup(props: { source: string; has_draft?: boolean }) {
  try {
    if (sessionStorage.getItem(STARTED)) return;
    sessionStorage.setItem(STARTED, "1");
  } catch { /* private mode */ }
  track("sign_up_start", props);
}

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

// Every country and its dialing code, as Clerk's own phone field lists them (@clerk/ui).
const CODES = "AF93 AX358 AL355 DZ213 AS1684 AD376 AO244 AI1264 AG1268 AR54 AM374 AW297 AC247 AU61 AT43 AZ994 BS1242 BH973 "
  + "BD880 BB1246 BY375 BE32 BZ501 BJ229 BM1441 BT975 BO591 BA387 BW267 BR55 IO246 VG1284 BN673 BG359 BF226 BI257 KH855 CM237 "
  + "CA1 CV238 BQ599 KY1345 CF236 TD235 CL56 CN86 CO57 KM269 CD243 CG242 CK682 CR506 CI225 HR385 CU53 CW599 CY357 CZ420 DK45 "
  + "DJ253 DM1767 DO1 EC593 EG20 SV503 GQ240 ER291 EE372 ET251 FK500 FO298 FJ679 FI358 FR33 GF594 PF689 GA241 GM220 GE995 DE49 "
  + "GH233 GI350 GR30 GL299 GD1473 GP590 GU1671 GT502 GN224 GW245 GY592 HT509 HN504 HK852 HU36 IS354 IN91 ID62 IR98 IQ964 IE353 "
  + "IL972 IT39 JM1876 JP81 JO962 KZ7 KE254 KI686 XK383 KW965 KG996 LA856 LV371 LB961 LS266 LR231 LY218 LI423 LT370 LU352 MO853 "
  + "MG261 MW265 MY60 MV960 ML223 MT356 MH692 MQ596 MR222 MU230 YT262 MX52 FM691 MD373 MC377 MN976 ME382 MS1664 MA212 MZ258 MM95 "
  + "NA264 NR674 NP977 NL31 NC687 NZ64 NI505 NE227 NG234 NU683 NF672 KP850 MK389 MP1670 NO47 OM968 PK92 PW680 PS970 PA507 PG675 "
  + "PY595 PE51 PH63 PL48 PT351 PR1 QA974 RE262 RO40 RU7 RW250 BL590 SH290 KN1869 LC1758 MF590 PM508 VC1784 WS685 SM378 ST239 "
  + "SA966 SN221 RS381 SC248 SL232 SG65 SX1721 SK421 SI386 SB677 SO252 ZA27 KR82 SS211 ES34 LK94 SD249 SR597 SZ268 SE46 CH41 "
  + "SY963 TW886 TJ992 TZ255 TH66 TL670 TG228 TK690 TO676 TT1868 TN216 TR90 TM993 TC1649 TV688 VI1340 UG256 UA380 AE971 GB44 "
  + "US1 UY598 UZ998 VU678 VA39 VE58 VN84 WF681 EH212 YE967 ZM260 ZW263";

/** The phone step's countries, [region, dialing code]. The SMS relay sends Saudi numbers from the Cycls sender, the
 *  rest through Twilio. */
export const PHONE_COUNTRIES = CODES.split(" ").map((t) => [t.slice(0, 2), t.slice(2)] as const);

/** Arabic-Indic and Persian digits as 0–9: what an Arabic keyboard types into a number or a code. */
export const latinDigits = (s: string) => s.replace(/[٠-٩۰-۹]/g, (d) => String(d.charCodeAt(0) & 15));

/** The number as Clerk wants it, +966551234567: a pasted international number as it is, otherwise the picked
 *  country's code and the local number without its leading 0 (05… at home is +966 5… abroad). */
export function toE164(country: string, typed: string) {
  const raw = latinDigits(typed).trim();
  if (/^(\+|00)/.test(raw)) return "+" + raw.replace(/^(\+|00)/, "").replace(/\D/g, "");
  return `+${country}${raw.replace(/\D/g, "").replace(/^0+/, "")}`;
}

/** A sign-up Clerk holds open for the phone alone: the email (or Google/Apple account) is done and the number is
 *  what's left. With Clerk's phone requirement off no sign-up ever waits on it, so the step never shows. */
export function needsPhone(signUp: { status: string | null; missingFields: string[]; unverifiedFields: string[] } | null | undefined) {
  if (signUp?.status !== "missing_requirements") return false;
  const open = [...signUp.missingFields, ...signUp.unverifiedFields];
  return open.length > 0 && open.every((f) => f === "phone_number");
}

/** First authed load: a just-created account nobody has counted is a sign-up —
 *  OAuth has no other moment, the redirect swallows it. */
export function detectSignup(user: { id: string; createdAt?: Date | string | null } | null | undefined, provider?: string | null) {
  if (!user?.id || !user.createdAt) return;
  if (counted().includes(user.id)) return;
  remember(user.id);
  let pending = false;
  try { pending = sessionStorage.getItem(PENDING) === "1"; sessionStorage.removeItem(PENDING); } catch { /* private mode */ }
  if (pending) return;   // the form already counted this account
  if (Date.now() - new Date(user.createdAt).getTime() < FRESH_MS) track("sign_up", { method: provider || "oauth" });
}
