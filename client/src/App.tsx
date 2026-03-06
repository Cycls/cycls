import { useEffect, useState } from "react";
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
  useUser,
} from "@clerk/clerk-react";
import { __experimental_useSubscription as useSubscription } from "@clerk/shared/react";
import { dark } from "@clerk/themes";
import { Chat } from "./components/chat";
import { useChat, AppConfig } from "./hooks/use-chat";

function ChatWithAuth() {
  const { messages, isStreaming, config, send, stop, clear, fetchConfig, setGetToken } =
    useChat("/api");
  const { getToken, signOut } = useAuth();
  const { user } = useUser();
  const clerk = useClerk();
  const { organization } = useOrganization();
  const { userMemberships, setActive } = useOrganizationList({ userMemberships: true });
  const { data: subscription } = useSubscription();

  useEffect(() => {
    setGetToken(() => getToken());
  }, [getToken, setGetToken]);

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  const orgs = (userMemberships?.data || []).map((m) => ({
    id: m.organization.id,
    name: m.organization.name,
    imageUrl: m.organization.imageUrl,
  }));

  return (
    <Chat
      messages={messages}
      isStreaming={isStreaming}
      onSend={send}
      onStop={stop}
      onClear={clear}
      onSignOut={() => signOut()}
      onManageAccount={() => clerk.openUserProfile()}
      onCreateOrg={() => clerk.openCreateOrganization()}
      onManageOrg={() => clerk.openOrganizationProfile()}
      onSwitchOrg={(orgId) => setActive?.({ organization: orgId || null })}
      activeOrg={organization ? { id: organization.id, name: organization.name, imageUrl: organization.imageUrl } : undefined}
      orgs={orgs}
      plan={subscription?.subscriptionItems?.[0]?.plan?.name}
      title={config?.header}
      user={user ? {
        name: user.fullName || user.firstName || "",
        email: user.primaryEmailAddress?.emailAddress || "",
        imageUrl: user.imageUrl,
      } : undefined}
    />
  );
}

function ChatNoAuth() {
  const { messages, isStreaming, config, send, stop, clear, fetchConfig } =
    useChat("/api");

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  return (
    <Chat
      messages={messages}
      isStreaming={isStreaming}
      onSend={send}
      onStop={stop}
      onClear={clear}
      title={config?.header}
    />
  );
}

function CustomSignIn() {
  const { isLoaded, signIn } = useSignIn();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");

  if (!isLoaded) return null;

  const handleGoogle = async () => {
    try {
      setIsLoading(true);
      setError("");
      await signIn.authenticateWithRedirect({
        strategy: "oauth_google",
        redirectUrl: "/sso-callback",
        redirectUrlComplete: "/",
      });
    } catch (err: unknown) {
      const clerkErr = err as { errors?: { message: string }[] };
      setError(clerkErr.errors?.[0]?.message || "Sign in failed");
      setIsLoading(false);
    }
  };

  const toggleDark = () => document.body.classList.toggle("dark");

  return (
    <div className="flex h-dvh w-full flex-col bg-background">
      <div className="fixed top-0 right-0 p-4">
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
      <main className="flex flex-1 flex-col items-center justify-center px-4">
        <div className="w-full max-w-sm">
          {/* Logo — two stars */}
          <div className="flex justify-center mb-8">
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
                Welcome to Cycls
              </h1>
              <p className="text-muted-foreground text-sm mt-1.5">
                Sign in to continue
              </p>
            </div>

            {error && (
              <div className="rounded-lg bg-red-500/10 border border-red-500/20 px-4 py-3 text-sm text-red-500 mb-4">
                {error}
              </div>
            )}

            <button
              onClick={handleGoogle}
              disabled={isLoading}
              className="flex w-full items-center justify-center gap-3 rounded-xl border border-border bg-background px-4 py-3 text-sm font-medium text-foreground hover:bg-secondary transition-colors disabled:opacity-50 cursor-pointer"
            >
              <svg className="size-4" viewBox="0 0 24 24">
                <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" />
                <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
                <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
              </svg>
              {isLoading ? "Connecting..." : "Continue with Google"}
            </button>

            <div className="mt-6 flex items-center gap-3">
              <div className="h-px flex-1 bg-border" />
              <span className="text-xs text-muted-foreground">or</span>
              <div className="h-px flex-1 bg-border" />
            </div>

            <p className="mt-4 text-center text-xs text-muted-foreground">
              More sign-in options coming soon
            </p>
          </div>

          <p className="mt-6 text-center text-xs text-muted-foreground">
            By continuing, you agree to our Terms of Service
          </p>
        </div>
      </main>
    </div>
  );
}

function useDarkMode() {
  const [isDark, setIsDark] = useState(document.body.classList.contains("dark"));
  useEffect(() => {
    const observer = new MutationObserver(() => {
      setIsDark(document.body.classList.contains("dark"));
    });
    observer.observe(document.body, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);
  return isDark;
}

export default function App() {
  const isDark = useDarkMode();
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/config")
      .then((r) => r.json())
      .then((c) => setConfig(c))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return null;

  const clerkKey = config?.auth ? (import.meta.env.VITE_CLERK_PUBLISHABLE_KEY || config?.pk) : null;

  if (!clerkKey) {
    return <ChatNoAuth />;
  }

  if (window.location.pathname === "/sso-callback") {
    return (
      <ClerkProvider publishableKey={clerkKey}>
        <AuthenticateWithRedirectCallback />
      </ClerkProvider>
    );
  }

  return (
    <ClerkProvider publishableKey={clerkKey} appearance={{ baseTheme: isDark ? dark : undefined }}>
      <SignedIn>
        <ChatWithAuth />
      </SignedIn>
      <SignedOut>
        <CustomSignIn />
      </SignedOut>
    </ClerkProvider>
  );
}
