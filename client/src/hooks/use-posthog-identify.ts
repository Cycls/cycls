import { useEffect, useRef } from "react";
import { identifyUser, resetUser, track } from "../lib/analytics";
import type { ClerkUser, SubscriptionSummary, OrgSummary } from "../lib/analytics";
import { identifyPush, resetPush } from "../lib/notifications";

export function usePostHogIdentify(
  enabled: boolean,
  user: ClerkUser | null | undefined,
  subscription: SubscriptionSummary | null | undefined,
  organization: OrgSummary | null | undefined,
  language: string,
) {
  const prevUserIdRef = useRef<string | null>(null);
  // canceledAt appearing or clearing while the page is open is the Manage
  // drawer at work: a cancellation or a resume. Baseline from the first loaded
  // subscription, so an old cancellation never re-fires.
  const cancelRef = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    if (!enabled || !user || !subscription) return;
    const now = subscription.canceledAt ? String(subscription.canceledAt) : null;
    if (cancelRef.current !== undefined && cancelRef.current !== now) {
      track(now ? "subscription_cancelled" : "subscription_resumed",
            { plan_name: subscription.planName, plan_period: subscription.planPeriod });
    }
    cancelRef.current = now;
  }, [enabled, user?.id, subscription?.canceledAt]);   // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    // Push targeting is by user id whether or not analytics is on.
    if (user) identifyPush(user.id); else resetPush();
    if (!enabled) return;

    if (user) {
      // No sign-in event here: that fact is PostHog's own $identify, and a new
      // account is our sign_up — a custom twin of either would double-count.
      identifyUser(user, {
        subscription: subscription || undefined,
        organization: organization || undefined,
        language,
      });
      prevUserIdRef.current = user.id;
    } else if (prevUserIdRef.current !== null) {
      track("user_signed_out", { user_id: prevUserIdRef.current });
      resetUser();
      prevUserIdRef.current = null;
    }
  }, [enabled, user, subscription, organization, language]);
}
