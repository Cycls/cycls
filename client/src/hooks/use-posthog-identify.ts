import { useEffect, useRef } from "react";
import { identifyUser, resetUser, track } from "../lib/posthog";
import type { ClerkUser, SubscriptionSummary, OrgSummary } from "../lib/posthog";

export function usePostHogIdentify(
  enabled: boolean,
  user: ClerkUser | null | undefined,
  subscription: SubscriptionSummary | null | undefined,
  organization: OrgSummary | null | undefined,
  language: string,
  method?: string | null,
) {
  const prevUserIdRef = useRef<string | null>(null);

  useEffect(() => {
    if (!enabled) return;

    if (user) {
      const isFirst = prevUserIdRef.current === null;
      identifyUser(user, {
        subscription: subscription || undefined,
        organization: organization || undefined,
        language,
      });
      if (isFirst) {
        const createdAt = user.createdAt ? new Date(user.createdAt).getTime() : 0;
        const isNewUser = createdAt > 0 && Date.now() - createdAt < 5 * 60 * 1000;
        track(isNewUser ? "user_signed_up" : "user_signed_in", {
          user_id: user.id,
          org_id: organization?.id,
          method: method || null,
        });
      }
      prevUserIdRef.current = user.id;
    } else if (prevUserIdRef.current !== null) {
      track("user_signed_out", { user_id: prevUserIdRef.current });
      resetUser();
      prevUserIdRef.current = null;
    }
  }, [enabled, user, subscription, organization, language, method]);
}
