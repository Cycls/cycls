// One pipe of canonical events (docs/notes/analytics.md). track() enriches once
// and fans out to the providers configured by Web().analytics(...) — each a
// plugin, each optionally scoped to an event allowlist. A provider may also
// bring flags (who sees a prompt or a card, with what payload) and surveys
// (questions authored on the platform) — docs/notes/engagement.md. Adding a
// vendor means adding a factory to PLUGINS, never touching a call site.
import posthog from "posthog-js";

const POSTHOG_KEY = "phc_2qafhOCTgCnygXsPEHOA0RBtJf5nvVsi7yIene4DWaF";
const POSTHOG_HOST = "https://us.i.posthog.com";

export type ProviderSpec = { provider: string; events?: string[] } & Record<string, unknown>;

export type Flag = { enabled: boolean; payload: unknown };

// A survey as the strip renders it — PostHog's shape is the reference; another
// vendor's plugin maps its own into this.
export type SurveyQuestion = {
  id?: string; type: string; question: string; description?: string | null;
  choices?: string[]; scale?: number; display?: string;
  lowerBoundLabel?: string; upperBoundLabel?: string;
};
export type Survey = {
  id: string; name: string; type: string; questions: SurveyQuestion[];
  current_iteration?: number | null; current_iteration_start_date?: string | null;
};

export type Flags = { on(cb: () => void): () => void; get(key: string): Flag };
export type Surveys = {
  /** The surveys this person should see right now, once the vendor has decided. */
  on(cb: (surveys: Survey[]) => void): void;
  /** The vendor's own survey events, in its own vocabulary — not on the pipe. */
  event(name: string, props: Record<string, unknown>): void;
};

type Provider = {
  name: string;
  events?: string[];   // allowlist; absent = every event
  send(event: string, props: Record<string, unknown>): void;
  register?(props: Record<string, unknown>): void;
  identify?(id: string, props: Record<string, unknown>): void;
  reset?(): void;
  setPerson?(props: Record<string, unknown>): void;
  flags?: Flags;
  surveys?: Surveys;
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
      setPerson: (p) => posthog.setPersonProperties(p),
      flags: {
        on: (cb) => posthog.onFeatureFlags(() => cb()),
        get: (key) => ({ enabled: !!posthog.isFeatureEnabled(key, { send_event: false }),
                         payload: posthog.getFeatureFlagPayload(key) }),
      },
      surveys: {
        // Surveys authored with the API presentation: the vendor targets, we render.
        on: (cb) => posthog.onSurveysLoaded((_, ctx) => {
          if (ctx?.isLoaded === false) return;
          posthog.getActiveMatchingSurveys((list) => {
            const surveys = list as unknown as Survey[];
            // Any other presentation makes PostHog draw its own widget over the page.
            for (const x of surveys) if (x.type !== "api")
              console.warn(`[cycls] survey "${x.name}" uses PostHog's ${x.type} presentation — set it to API so it renders in the strip`);
            cb(surveys);
          });
        }),
        event: (name, props) => posthog.capture(name, props),
      },
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

export const flagsProvider = (): Flags | null => providers.find((p) => p.flags)?.flags ?? null;
export const surveysProvider = (): Surveys | null => providers.find((p) => p.surveys)?.surveys ?? null;

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

/** Facts about the person, not the session — what a flag condition can read. */
export function setPerson(props: Record<string, unknown>) {
  for (const p of providers) p.setPerson?.(props);
}

export function register(props: Record<string, unknown>) {
  superProps = { ...superProps, ...props };
  for (const p of providers) p.register?.(props);
}

