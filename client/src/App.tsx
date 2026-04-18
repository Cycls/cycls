import { useEffect, useRef, useState } from "react";
import { useDarkMode } from "./hooks/use-dark-mode";
import {
  AuthenticateWithRedirectCallback,
  ClerkProvider,
  SignedIn,
  SignedOut,
  useAuth,
  useClerk,
  useOrganization,
  useOrganizationList,
  useSignIn,
  useSignUp,
  useUser,
} from "@clerk/clerk-react";
import { useSubscription } from "@clerk/clerk-react/experimental";
import { dark } from "@clerk/themes";
import { arSA } from "@clerk/localizations";
import { useLang, setLang, t } from "./lib/i18n";
import { Chat } from "./components/chat";
import { SharedView } from "./components/shared-view";
import { useChat, AppConfig } from "./hooks/use-chat";
import { useFiles } from "./hooks/use-files";
import { usePostHogIdentify } from "./hooks/use-posthog-identify";
import { initPostHog, setAgentDomain, track, register } from "./lib/posthog";

function ChatApp({ config }: { config: AppConfig | null }) {
  const { messages, isStreaming, sessionLoading, sessionId, send, retry, stop, clear, share, listShares, deleteShare, listSessions, loadSession, deleteSession, setGetToken, uploadFile, authHeaders } =
    useChat();
  const { entries, path, loading, list, upload, mkdir, rename, remove, openFile, setGetToken: setFilesToken } =
    useFiles();
  const { getToken, signOut } = useAuth();
  const { user } = useUser();
  const clerk = useClerk();
  const { organization } = useOrganization();
  const { userMemberships, setActive } = useOrganizationList({ userMemberships: true });
  const { data: subscription } = useSubscription({ for: organization ? "organization" : "user" });
  const lang = useLang();

  const subItem = subscription?.subscriptionItems?.[0];
  const subSummary = subItem ? {
    planName: subItem.plan.name,
    status: subItem.status,
    amount: subItem.amount,
    planPeriod: subItem.planPeriod,
    periodEnd: subItem.periodEnd,
    canceledAt: subItem.canceledAt,
  } : undefined;
  const orgSummary = organization ? {
    id: organization.id,
    name: organization.name,
    imageUrl: organization.imageUrl,
  } : undefined;

  usePostHogIdentify(
    !!config?.analytics,
    user,
    subSummary,
    orgSummary,
    lang,
    clerk?.client?.lastAuthenticationStrategy,
  );

  useEffect(() => {
    setGetToken(() => getToken());
    setFilesToken(() => getToken());
  }, [getToken, setGetToken, setFilesToken]);

  // Auto-send ?q= param on first load
  const qSent = useRef(false);
  useEffect(() => {
    if (qSent.current) return;
    const q = new URLSearchParams(window.location.search).get("q");
    if (q) {
      qSent.current = true;
      window.history.replaceState({}, "", window.location.pathname);
      send(q, undefined, "url_param");
    }
  }, [send]);

  const handleShare = async (title: string = "") => {
    const author = user ? {
      name: user.fullName || user.firstName || "",
      imageUrl: user.imageUrl,
      org: organization ? { name: organization.name, imageUrl: organization.imageUrl } : undefined,
    } : undefined;
    return await share(title, author);
  };

  const orgs = (userMemberships?.data || []).map((m) => ({
    id: m.organization.id,
    name: m.organization.name,
    imageUrl: m.organization.imageUrl,
  }));

  return (
    <Chat
      messages={messages}
      isStreaming={isStreaming}
      sessionLoading={sessionLoading}
      onSend={send}
      onStop={stop}
      onClear={clear}
      onRetry={retry}
      onShare={handleShare}
      onListShares={listShares}
      onDeleteShare={deleteShare}
      onListSessions={listSessions}
      onLoadSession={loadSession}
      onDeleteSession={deleteSession}
      sessionId={sessionId}
      onSignOut={() => signOut()}
      onManageAccount={() => clerk.openUserProfile()}
      onCreateOrg={() => clerk.openCreateOrganization()}
      onManageOrg={() => clerk.openOrganizationProfile()}
      onSwitchOrg={(orgId) => { setActive?.({ organization: orgId || null }); clear(); }}
      activeOrg={organization ? { id: organization.id, name: organization.name, imageUrl: organization.imageUrl } : undefined}
      orgs={orgs}
      plan={subscription?.subscriptionItems?.[0] ? {
        name: subscription.subscriptionItems[0].plan.name,
        status: subscription.subscriptionItems[0].status,
        periodEnd: subscription.subscriptionItems[0].periodEnd,
        canceledAt: subscription.subscriptionItems[0].canceledAt,
        amount: subscription.subscriptionItems[0].amount,
        planPeriod: subscription.subscriptionItems[0].planPeriod,
      } : undefined}
      name={config?.name}
      passMetadata={config?.pass_metadata}
      user={user ? {
        name: user.fullName || user.firstName || "",
        email: user.primaryEmailAddress?.emailAddress || "",
        imageUrl: user.imageUrl,
      } : undefined}
      uploadFile={uploadFile}
      authHeaders={authHeaders}
      voice={config?.voice}
      files={{
        entries, path, loading,
        onNavigate: list,
        onUpload: upload,
        onMkdir: mkdir,
        onRename: rename,
        onDelete: remove,
        onOpenFile: openFile,
      }}
    />
  );
}

function ChatNoAuth({ config }: { config: AppConfig | null }) {
  const { messages, isStreaming, send, retry, stop, clear, uploadFile } =
    useChat();
  const { entries, path, loading, list, upload, mkdir, rename, remove, openFile } =
    useFiles();

  // Auto-send ?q= param on first load
  const qSent = useRef(false);
  useEffect(() => {
    if (qSent.current) return;
    const q = new URLSearchParams(window.location.search).get("q");
    if (q) {
      qSent.current = true;
      window.history.replaceState({}, "", window.location.pathname);
      send(q, undefined, "url_param");
    }
  }, [send]);

  return (
    <Chat
      messages={messages}
      isStreaming={isStreaming}
      onSend={send}
      onStop={stop}
      onClear={clear}
      onRetry={retry}
      name={config?.name}
      passMetadata={config?.pass_metadata}
      uploadFile={uploadFile}
      files={{
        entries, path, loading,
        onNavigate: list,
        onUpload: upload,
        onMkdir: mkdir,
        onRename: rename,
        onDelete: remove,
        onOpenFile: openFile,
      }}
    />
  );
}

const PERSIST_KEYS = ["q", "plans"] as const;
const ssKey = (k: string) => `cycls_${k}`;

function stashParams() {
  const params = new URLSearchParams(window.location.search);
  for (const k of PERSIST_KEYS) {
    const v = params.get(k);
    if (v) sessionStorage.setItem(ssKey(k), v);
  }
}

function popParams(): string {
  const params = new URLSearchParams();
  for (const k of PERSIST_KEYS) {
    const v = sessionStorage.getItem(ssKey(k));
    if (v) { params.set(k, v); sessionStorage.removeItem(ssKey(k)); }
  }
  return params.toString() ? `/?${params}` : "/";
}

function SSOCallback() {
  const dest = popParams();
  return (
    <AuthenticateWithRedirectCallback
      signInForceRedirectUrl={dest}
      signUpForceRedirectUrl={dest}
    />
  );
}

function CustomSignIn() {
  const { isLoaded, signIn, setActive } = useSignIn();
  const { signUp, setActive: setSignUpActive } = useSignUp();
  const { client } = useClerk();
  const lang = useLang();
  const isAr = lang === "ar";
  const lastStrategy = client?.lastAuthenticationStrategy;
  const [isLoading, setIsLoading] = useState<string | false>(false);
  const [error, setError] = useState("");
  const [noticeProvider, setNoticeProvider] = useState("");
  const [mode, setMode] = useState<"sign-in" | "sign-up" | "forgot-password">("sign-in");
  const [step, setStep] = useState<"form" | "verify">("form");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [newPassword, setNewPassword] = useState("");

  if (!isLoaded) return null;

  const resetForm = () => {
    setError("");
    setStep("form");
    setEmail("");
    setPassword("");
    setCode("");
    setNewPassword("");
  };

  const switchMode = (m: "sign-in" | "sign-up" | "forgot-password") => {
    resetForm();
    setMode(m);
  };

  const inAppBrowser = (() => {
    const ua = navigator.userAgent;
    if (/FBAN|FBIOS|FB_IAB/i.test(ua)) return "Facebook";
    if (/Instagram/i.test(ua)) return "Instagram";
    if (/LinkedInApp/i.test(ua)) return "LinkedIn";
    if (/Snapchat/i.test(ua)) return "Snapchat";
    if (/Twitter/i.test(ua)) return "Twitter";
    if (/TikTok|trill/i.test(ua)) return "TikTok";
    return null;
  })();

  const handleOAuth = async (strategy: "oauth_google" | "oauth_apple") => {
    if (inAppBrowser) {
      const provider = strategy === "oauth_google" ? "Google" : "Apple";
      setNoticeProvider(provider);
      return;
    }
    try {
      setIsLoading(strategy);
      setError("");
      track("sign_in_attempted", { method: strategy, step: "oauth_redirect" });
      stashParams();
      const params = new URLSearchParams(window.location.search);
      const redirectUrlComplete = params.toString() ? `/?${params}` : "/";
      await signUp!.authenticateWithRedirect({
        strategy,
        redirectUrl: "/sso-callback",
        redirectUrlComplete,
      });
    } catch (err: unknown) {
      const clerkErr = err as { errors?: { message: string }[] };
      setError(clerkErr.errors?.[0]?.message || "Sign in failed");
      setIsLoading(false);
    }
  };

  const handleSignIn = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      setIsLoading("form");
      setError("");
      track("sign_in_attempted", { method: "password", step: "form" });
      const result = await signIn!.create({ identifier: email, password });
      if (result.status === "complete") {
        await setActive!({ session: result.createdSessionId });
      } else if (result.status === "needs_first_factor") {
        setStep("verify");
      }
    } catch (err: unknown) {
      const clerkErr = err as { errors?: { message: string }[] };
      setError(clerkErr.errors?.[0]?.message || "Sign in failed");
    } finally {
      setIsLoading(false);
    }
  };

  const handleSignInVerify = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      setIsLoading("form");
      setError("");
      track("sign_in_attempted", { method: "email_code", step: "verify" });
      const result = await signIn!.attemptFirstFactor({ strategy: "email_code", code });
      if (result.status === "complete") {
        await setActive!({ session: result.createdSessionId });
      }
    } catch (err: unknown) {
      const clerkErr = err as { errors?: { message: string }[] };
      setError(clerkErr.errors?.[0]?.message || "Verification failed");
    } finally {
      setIsLoading(false);
    }
  };

  const handleSignUp = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      setIsLoading("form");
      setError("");
      track("sign_up_attempted", { method: "password", step: "form" });
      const result = await signUp!.create({ emailAddress: email, password });
      if (result.status === "complete") {
        await setSignUpActive!({ session: result.createdSessionId });
      } else {
        await signUp!.prepareEmailAddressVerification({ strategy: "email_code" });
        setStep("verify");
      }
    } catch (err: unknown) {
      const clerkErr = err as { errors?: { message: string }[] };
      setError(clerkErr.errors?.[0]?.message || "Sign up failed");
    } finally {
      setIsLoading(false);
    }
  };

  const handleSignUpVerify = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      setIsLoading("form");
      setError("");
      track("sign_up_attempted", { method: "email_code", step: "verify" });
      const result = await signUp!.attemptEmailAddressVerification({ code });
      if (result.status === "complete") {
        await setSignUpActive!({ session: result.createdSessionId });
      }
    } catch (err: unknown) {
      const clerkErr = err as { errors?: { message: string }[] };
      setError(clerkErr.errors?.[0]?.message || "Verification failed");
    } finally {
      setIsLoading(false);
    }
  };

  const handleForgotPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      setIsLoading("form");
      setError("");
      await signIn!.create({ strategy: "reset_password_email_code", identifier: email });
      setStep("verify");
    } catch (err: unknown) {
      const clerkErr = err as { errors?: { message: string }[] };
      setError(clerkErr.errors?.[0]?.message || "Reset failed");
    } finally {
      setIsLoading(false);
    }
  };

  const handleResetVerify = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      setIsLoading("form");
      setError("");
      const result = await signIn!.attemptFirstFactor({
        strategy: "reset_password_email_code",
        code,
        password: newPassword,
      });
      if (result.status === "complete") {
        await setActive!({ session: result.createdSessionId });
      }
    } catch (err: unknown) {
      const clerkErr = err as { errors?: { message: string }[] };
      setError(clerkErr.errors?.[0]?.message || "Reset failed");
    } finally {
      setIsLoading(false);
    }
  };

  const toggleDark = () => {
    document.body.classList.toggle("dark");
    track("theme_changed", {
      to: document.body.classList.contains("dark") ? "dark" : "light",
      source: "sign_in",
    });
  };

  const inputClass = "w-full rounded-xl border border-border bg-background px-4 py-3 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring";
  const submitClass = "flex w-full items-center justify-center rounded-xl border border-border bg-background px-4 py-3 text-sm font-medium text-foreground hover:bg-secondary transition-colors disabled:opacity-50 cursor-pointer";

  return (
    <div className="flex h-dvh w-full flex-col bg-background">
      <div className="fixed top-0 right-0 p-4 flex items-center gap-1" dir="ltr">
        <button
          onClick={() => {
            const next = isAr ? "en" : "ar";
            setLang(next);
            track("language_changed", { to: next, source: "sign_in" });
          }}
          className="text-muted-foreground hover:text-foreground hover:bg-secondary/80 rounded-lg p-2 transition-colors cursor-pointer"
          aria-label="Toggle language"
        >
          <span className="text-xs font-medium w-4 h-4 flex items-center justify-center">{isAr ? "En" : "عربي"}</span>
        </button>
        <button
          onClick={toggleDark}
          className="text-muted-foreground hover:text-foreground hover:bg-secondary/80 rounded-lg p-2 transition-colors cursor-pointer"
          aria-label="Toggle theme"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
          </svg>
        </button>
      </div>
      <main className="flex flex-1 flex-col items-center justify-center px-4 py-16">
        <div className="w-full max-w-sm">
          {/* Logo — two stars */}
          <div className="hidden sm:flex justify-center mb-8">
            <svg viewBox="-1 -1 25 23" className="h-12 text-foreground">
              {/* Big star — filled */}
              <path fill="currentColor" d="M 5.248 0 L 5.734 1.654 C 6.164 3.153 7.345 4.33 8.844 4.765 L 10.496 5.241 L 8.844 5.718 C 7.345 6.152 6.164 7.329 5.734 8.829 L 5.248 10.496 L 4.762 8.843 C 4.332 7.343 3.152 6.166 1.652 5.732 L 0 5.255 L 1.652 4.779 C 3.152 4.344 4.332 3.167 4.762 1.668 L 5.248 0 Z" />
              {/* Small star — stroke */}
              <path fill="none" stroke="currentColor" strokeWidth={0.6} d="M 17.359 13.159 C 17.493 13.671 18.909 15.02 19.38 15.192 C 18.909 15.31 17.516 16.704 17.359 17.226 C 17.225 16.714 15.89 15.308 15.338 15.192 C 15.89 14.962 17.211 13.671 17.359 13.159 Z" />
            </svg>
          </div>

          {/* Card */}
          <div className="rounded-2xl border border-border bg-card p-8">
            <div className="text-center mb-6">
              <h1 className="text-foreground text-xl font-semibold tracking-tight">
                {t("welcomeTo")}
              </h1>
              <p className="text-muted-foreground text-sm mt-1.5">
                {t("signInToContinue")}
              </p>
            </div>

            {noticeProvider && inAppBrowser && (
              <div className="rounded-lg bg-amber-500/10 border border-amber-500/20 px-4 py-3 text-sm text-amber-600 dark:text-amber-400 mb-4">
                {t("openInBrowser").replace("{provider}", noticeProvider).replace("{app}", inAppBrowser)}
              </div>
            )}

            {error && (
              <div className="rounded-lg bg-red-500/10 border border-red-500/20 px-4 py-3 text-sm text-red-500 mb-4">
                {error}
              </div>
            )}

            {/* OAuth buttons */}
            <div className="space-y-3">
              <div className={`relative${isLoading ? " opacity-50" : ""} transition-opacity`}>
                {lastStrategy === "oauth_google" && (
                  <span className="absolute top-0 -translate-y-1/2 inset-x-0 flex justify-center">
                    <span className="bg-card text-muted-foreground text-[10px] leading-none px-2 py-0.5 rounded-full">{t("lastUsed")}</span>
                  </span>
                )}
                <button
                  onClick={() => handleOAuth("oauth_google")}
                  disabled={!!isLoading}
                  className={`flex w-full items-center justify-center gap-3 rounded-xl border bg-background px-4 py-3 text-sm font-medium text-foreground hover:bg-secondary transition-colors cursor-pointer ${lastStrategy === "oauth_google" ? "border-foreground/30" : "border-border"}`}
                >
                  <svg className="size-4" viewBox="0 0 24 24">
                    <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" />
                    <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                    <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
                    <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
                  </svg>
                  {isLoading === "oauth_google" ? t("connecting") : t("continueWithGoogle")}
                </button>
              </div>

              <div className={`relative${isLoading ? " opacity-50" : ""} transition-opacity`}>
                {lastStrategy === "oauth_apple" && (
                  <span className="absolute top-0 -translate-y-1/2 inset-x-0 flex justify-center">
                    <span className="bg-card text-muted-foreground text-[10px] leading-none px-2 py-0.5 rounded-full">{t("lastUsed")}</span>
                  </span>
                )}
                <button
                  onClick={() => handleOAuth("oauth_apple")}
                  disabled={!!isLoading}
                  className={`flex w-full items-center justify-center gap-3 rounded-xl border bg-background px-4 py-3 text-sm font-medium text-foreground hover:bg-secondary transition-colors cursor-pointer ${lastStrategy === "oauth_apple" ? "border-foreground/30" : "border-border"}`}
                >
                  <svg className="size-4" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M17.05 20.28c-.98.95-2.05.88-3.08.4-1.09-.5-2.08-.48-3.24 0-1.44.62-2.2.44-3.06-.4C2.79 15.25 3.51 7.59 9.05 7.31c1.35.07 2.29.74 3.08.8 1.18-.24 2.31-.93 3.57-.84 1.51.12 2.65.72 3.4 1.8-3.12 1.87-2.38 5.98.48 7.13-.57 1.5-1.31 2.99-2.54 4.09zM12.03 7.25c-.15-2.23 1.66-4.07 3.74-4.25.29 2.58-2.34 4.5-3.74 4.25z" />
                  </svg>
                  {isLoading === "oauth_apple" ? t("connecting") : t("continueWithApple")}
                </button>
              </div>
            </div>

            <div className="mt-6 flex items-center gap-3">
              <div className="h-px flex-1 bg-border" />
              <span className="text-xs text-muted-foreground">{t("or")}</span>
              <div className="h-px flex-1 bg-border" />
            </div>

            {/* Email/password forms */}
            <div className="mt-6">
              {mode === "sign-in" && step === "form" && (
                <form onSubmit={handleSignIn} className="space-y-3">
                  <input
                    type="email"
                    placeholder={t("email")}
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className={inputClass}
                    required
                    autoComplete="email"
                  />
                  <input
                    type="password"
                    placeholder={t("password")}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className={inputClass}
                    required
                    autoComplete="current-password"
                  />
                  <button type="submit" disabled={!!isLoading} className={submitClass}>
                    {t("signIn")}
                  </button>
                  <button
                    type="button"
                    onClick={() => switchMode("forgot-password")}
                    className="w-full text-center text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
                  >
                    {t("forgotPassword")}
                  </button>
                </form>
              )}

              {mode === "sign-in" && step === "verify" && (
                <form onSubmit={handleSignInVerify} className="space-y-3">
                  <input
                    type="text"
                    placeholder={t("verificationCode")}
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    className={inputClass}
                    required
                    autoComplete="one-time-code"
                  />
                  <button type="submit" disabled={!!isLoading} className={submitClass}>
                    {t("signIn")}
                  </button>
                </form>
              )}

              {mode === "sign-up" && step === "form" && (
                <form onSubmit={handleSignUp} className="space-y-3">
                  <input
                    type="email"
                    placeholder={t("email")}
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className={inputClass}
                    required
                    autoComplete="email"
                  />
                  <input
                    type="password"
                    placeholder={t("password")}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className={inputClass}
                    required
                    autoComplete="new-password"
                  />
                  <div id="clerk-captcha" />
                  <button type="submit" disabled={!!isLoading} className={submitClass}>
                    {t("signUp")}
                  </button>
                </form>
              )}

              {mode === "sign-up" && step === "verify" && (
                <form onSubmit={handleSignUpVerify} className="space-y-3">
                  <input
                    type="text"
                    placeholder={t("verificationCode")}
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    className={inputClass}
                    required
                    autoComplete="one-time-code"
                  />
                  <button type="submit" disabled={!!isLoading} className={submitClass}>
                    {t("signUp")}
                  </button>
                </form>
              )}

              {mode === "forgot-password" && step === "form" && (
                <form onSubmit={handleForgotPassword} className="space-y-3">
                  <input
                    type="email"
                    placeholder={t("email")}
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className={inputClass}
                    required
                    autoComplete="email"
                  />
                  <button type="submit" disabled={!!isLoading} className={submitClass}>
                    {t("sendCode")}
                  </button>
                </form>
              )}

              {mode === "forgot-password" && step === "verify" && (
                <form onSubmit={handleResetVerify} className="space-y-3">
                  <input
                    type="text"
                    placeholder={t("verificationCode")}
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    className={inputClass}
                    required
                    autoComplete="one-time-code"
                  />
                  <input
                    type="password"
                    placeholder={t("newPassword")}
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    className={inputClass}
                    required
                    autoComplete="new-password"
                  />
                  <button type="submit" disabled={!!isLoading} className={submitClass}>
                    {t("resetPassword")}
                  </button>
                </form>
              )}
            </div>

            {/* Mode toggle links */}
            <div className="mt-4 text-center text-xs text-muted-foreground">
              {mode === "sign-in" && (
                <button onClick={() => switchMode("sign-up")} className="hover:text-foreground transition-colors cursor-pointer">
                  {t("noAccount")} <span className="font-medium">{t("signUp")}</span>
                </button>
              )}
              {mode === "sign-up" && (
                <button onClick={() => switchMode("sign-in")} className="hover:text-foreground transition-colors cursor-pointer">
                  {t("hasAccount")} <span className="font-medium">{t("signIn")}</span>
                </button>
              )}
              {mode === "forgot-password" && (
                <button onClick={() => switchMode("sign-in")} className="hover:text-foreground transition-colors cursor-pointer">
                  {t("backToSignIn")}
                </button>
              )}
            </div>
          </div>

          <p className="mt-6 text-center text-xs text-muted-foreground">
            {t("termsOfService")}
          </p>
        </div>
      </main>
    </div>
  );
}

export default function App() {
  const isDark = useDarkMode();
  const lang = useLang();
  const inlined = (window as any).__CONFIG__;
  const [config, setConfig] = useState<AppConfig | null>(inlined || null);
  const [loading, setLoading] = useState(!inlined);

  useEffect(() => {
    if (!inlined) {
      fetch("/config")
        .then((r) => r.json())
        .then((c) => setConfig(c))
        .catch(() => {})
        .finally(() => setLoading(false));
    }
  }, []);

  useEffect(() => {
    if (config?.analytics) {
      initPostHog();
      setAgentDomain(config.name);
    }
  }, [config?.analytics, config?.name]);

  useEffect(() => {
    register({ theme: isDark ? "dark" : "light", language: lang });
  }, [isDark, lang]);

  const sharedMatch = window.location.pathname.match(/^\/shared\/(.+)/);
  if (sharedMatch) {
    return <SharedView path={sharedMatch[1]} />;
  }

  if (loading) return null;

  const clerkKey = config?.auth ? (import.meta.env.VITE_CLERK_PUBLISHABLE_KEY || config?.pk) : null;

  if (!clerkKey) {
    return <ChatNoAuth config={config} />;
  }

  if (window.location.pathname === "/sso-callback") {
    return (
      <ClerkProvider publishableKey={clerkKey}>
        <SSOCallback />
      </ClerkProvider>
    );
  }

  return (
    <ClerkProvider publishableKey={clerkKey} appearance={{ baseTheme: isDark ? dark : undefined }} localization={lang === "ar" ? arSA : undefined}>
      <SignedIn>
        <ChatApp config={config} />
      </SignedIn>
      <SignedOut>
        <CustomSignIn />
      </SignedOut>
    </ClerkProvider>
  );
}
