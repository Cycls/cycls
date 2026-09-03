import { useEffect, useRef } from "react";
import { identifyUser, resetUser, track } from "../lib/posthog";
import type { ClerkUser, SubscriptionSummary, OrgSummary } from "../lib/posthog";

export function usePostHogIdentify(
  enabled: boolean,
  user: ClerkUser | null | undefined,
  subscription: SubscriptionSummary | null | undefined,
  organization: OrgSummary | null | undefined,
  language: string,
) {
  const prevUserIdRef = useRef<string | null>(null);

  useEffect(() => {
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
