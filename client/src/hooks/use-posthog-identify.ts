import { useEffect, useRef } from "react";
import { identifyUser, resetUser, track } from "../lib/analytics";
import type { ClerkUser, OrgSummary } from "../lib/analytics";
import { identifyPush, resetPush } from "../lib/notifications";

export function usePostHogIdentify(
  enabled: boolean,
  user: ClerkUser | null | undefined,
  organization: OrgSummary | null | undefined,
  language: string,
  plan?: string | null,
) {
  const prevUserIdRef = useRef<string | null>(null);

  useEffect(() => {
    // Push targeting is by user id whether or not analytics is on.
    if (user) identifyPush(user.id); else resetPush();
    if (!enabled) return;

    if (user) {
      // No sign-in event here: that fact is PostHog's own $identify, and a new
      // account is our sign_up — a custom twin of either would double-count.
      identifyUser(user, {
        organization: organization || undefined,
        language,
        plan,
      });
      prevUserIdRef.current = user.id;
    } else if (prevUserIdRef.current !== null) {
      track("user_signed_out", { user_id: prevUserIdRef.current });
      resetUser();
      prevUserIdRef.current = null;
    }
  }, [enabled, user, organization, language, plan]);
}
