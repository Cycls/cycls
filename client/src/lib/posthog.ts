// One pipe of canonical events (docs/notes/analytics.md). track() enriches once
// and fans out to the providers configured by Web().analytics(...) — each a
// plugin, each optionally scoped to an event allowlist. Adding a destination
// means adding a factory to PLUGINS, never touching a call site.
import posthog from "posthog-js";

const POSTHOG_KEY = "phc_2qafhOCTgCnygXsPEHOA0RBtJf5nvVsi7yIene4DWaF";
const POSTHOG_HOST = "https://us.i.posthog.com";

export type ProviderSpec = { provider: string; events?: string[] } & Record<string, unknown>;

type Provider = {
  name: string;
  events?: string[];   // allowlist; absent = every event
  send(event: string, props: Record<string, unknown>): void;
  register?(props: Record<string, unknown>): void;
  identify?(id: string, props: Record<string, unknown>): void;
  reset?(): void;
};

let initialized = false;   // posthog-js may only init once per page

const PLUGINS: Record<string, (spec: ProviderSpec) => Provider | null> = {
  posthog: (spec) => {
    if (!initialized) {
      posthog.init((spec.key as string) || POSTHOG_KEY, {
        api_host: (spec.host as string) || POSTHOG_HOST,
        person_profiles: "identified_only",
        capture_pageview: true,
        capture_pageleave: true,
        autocapture: false,
        persistence: "localStorage",
      });
      initialized = true;
    }
    return {
      name: "posthog", events: spec.events,
      send: (e, p) => posthog.capture(e, p),
      register: (p) => posthog.register(p),
      identify: (id, p) => posthog.identify(id, p),
      reset: () => posthog.reset(),
    };
  },
  // GTM reads the same canonical events off the dataLayer, names verbatim —
  // Web().analytics(GTM(...)) injects the container server-side, so without
  // one window.dataLayer is absent and the push no-ops.
  gtm: (spec) => ({
    name: "gtm", events: spec.events,
    send: (e, p) => (window as unknown as { dataLayer?: unknown[] }).dataLayer?.push({ event: e, ...p }),
  }),
};

let providers: Provider[] = [];
let superProps: Record<string, unknown> = {};

export function initAnalytics(specs?: ProviderSpec[] | null) {
  for (const s of specs || []) {
    if (providers.some((p) => p.name === s.provider)) continue;
    const p = PLUGINS[s.provider]?.(s);
    if (p) providers.push(p);
  }
}

export function _resetProviders() {   // tests only
  providers = [];
  superProps = {};
}

function getAgentDomain() {
  if (typeof window === "undefined") return "unknown";
  return window.location.hostname;
}

export function setAgentDomain(agentName?: string) {
  const domain = getAgentDomain();
  register({
    agent_domain: domain,
    agent_subdomain: domain.split(".")[0],
    agent_name: agentName || null,
  });
}

export type ClerkUser = {
  id: string;
  fullName?: string | null;
  firstName?: string | null;
  lastName?: string | null;
  imageUrl?: string;
  createdAt?: Date | string | null;
  primaryEmailAddress?: { emailAddress?: string } | null;
  emailAddresses?: { emailAddress?: string }[];
};

export type SubscriptionSummary = {
  planName?: string;
  status?: string;
  amount?: unknown;
  planPeriod?: string;
  periodEnd?: Date | string | null;
  canceledAt?: Date | string | null;
};

export type OrgSummary = {
  id?: string;
  name?: string;
  imageUrl?: string;
};

export type IdentifyExtras = {
  subscription?: SubscriptionSummary;
  organization?: OrgSummary;
  language?: string;
};

export function identifyUser(user: ClerkUser, extras: IdentifyExtras = {}) {
  if (!user) return;

  const email =
    user.primaryEmailAddress?.emailAddress ||
    user.emailAddresses?.[0]?.emailAddress;

  const props: Record<string, unknown> = {
    email,
    name:
      user.fullName ||
      `${user.firstName || ""} ${user.lastName || ""}`.trim() ||
      undefined,
    first_name: user.firstName || undefined,
    last_name: user.lastName || undefined,
    avatar_url: user.imageUrl,
    created_at: user.createdAt,
  };

  if (extras.subscription) {
    const s = extras.subscription;
    props.plan_name = s.planName;
    props.plan_status = s.status;
    props.plan_amount = s.amount;
    props.plan_period = s.planPeriod;
    props.plan_period_end = s.periodEnd;
    props.plan_canceled_at = s.canceledAt;
    props.is_paid = !!s.planName && s.planName.toLowerCase() !== "free";
  } else {
    props.is_paid = false;
  }

  if (extras.organization) {
    props.org_id = extras.organization.id;
    props.org_name = extras.organization.name;
    props.org_image_url = extras.organization.imageUrl;
  }

  if (extras.language) props.language = extras.language;

  const clean = Object.fromEntries(
    Object.entries(props).filter(([, v]) => v != null && v !== ""),
  );

  for (const p of providers) p.identify?.(user.id, clean);
}

export function resetUser() {
  for (const p of providers) p.reset?.();
}

export function track(event: string, props: Record<string, unknown> = {}) {
  for (const p of providers) {
    if (p.events && !p.events.includes(event)) continue;
    // Providers with native super-props (posthog) attach them themselves;
    // the rest get the bus's registered props merged in.
    p.send(event, p.register ? props : { ...superProps, ...props });
  }
}

export function register(props: Record<string, unknown>) {
  superProps = { ...superProps, ...props };
  for (const p of providers) p.register?.(props);
}

export { posthog };
