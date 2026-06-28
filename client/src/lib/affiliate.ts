// Affiliate / referral tracking. Vendor (Rewardful) is encapsulated here — the
// rest of the app calls initAffiliate / convertReferral, so swapping providers
// touches only this file.
//
// Cross-domain note: the referral cookie is captured on whatever domain runs
// this. Cycls's landing (cycls.com) and agents (*.cycls.ai) are different
// registrable domains, so the landing must forward the referral in the URL
// (Rewardful data-domains / ?via=) for it to land on .cycls.ai. Here we just
// load the tracker so an incoming ?via= is captured and convert() can fire.

let initialized = false;

export function initAffiliate(apiKey: string) {
  if (initialized || !apiKey || typeof window === "undefined") return;
  initialized = true;
  // Rewardful queue shim — buffers calls until rw.js loads.
  const w = window as unknown as { _rwq?: string; rewardful?: ((...a: unknown[]) => void) & { q?: unknown[] } };
  w._rwq = "rewardful";
  w.rewardful = w.rewardful || function (...args: unknown[]) { (w.rewardful!.q = w.rewardful!.q || []).push(args); };
  const s = document.createElement("script");
  s.async = true;
  s.src = "https://r.wdfl.co/rw.js";
  s.setAttribute("data-rewardful", apiKey);
  document.head.appendChild(s);
}

// Report a conversion after checkout. email must match the Stripe customer.
export function convertReferral(email: string) {
  if (!initialized || !email) return;
  window.rewardful?.("convert", { email });
}
