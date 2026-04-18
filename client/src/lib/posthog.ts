import posthog from "posthog-js";

const POSTHOG_KEY = "phc_2qafhOCTgCnygXsPEHOA0RBtJf5nvVsi7yIene4DWaF";
const POSTHOG_HOST = "https://us.i.posthog.com";

let initialized = false;

export function initPostHog() {
  if (initialized) return;
  posthog.init(POSTHOG_KEY, {
    api_host: POSTHOG_HOST,
    person_profiles: "identified_only",
    capture_pageview: true,
    capture_pageleave: true,
    autocapture: false,
    persistence: "localStorage",
  });
  initialized = true;
}

function getAgentDomain() {
  if (typeof window === "undefined") return "unknown";
  return window.location.hostname;
}

export function setAgentDomain(agentName?: string) {
  if (!initialized) return;
  const domain = getAgentDomain();
  posthog.register({
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
  if (!initialized || !user) return;

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

  posthog.identify(user.id, clean);
}

export function resetUser() {
  if (!initialized) return;
  posthog.reset();
}

export function track(event: string, props: Record<string, unknown> = {}) {
  if (!initialized) return;
  posthog.capture(event, props);
}

export function register(props: Record<string, unknown>) {
  if (!initialized) return;
  posthog.register(props);
}

export { posthog };
