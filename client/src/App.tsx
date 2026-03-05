import { useEffect, useState } from "react";
import {
  AuthenticateWithRedirectCallback,
  ClerkProvider,
  SignedIn,
  SignedOut,
  useAuth,
  useSignIn,
  useUser,
} from "@clerk/clerk-react";
import { Chat } from "./components/chat";
import { useChat } from "./hooks/use-chat";

const CLERK_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY;

function ChatWithAuth() {
  const { messages, isStreaming, config, send, stop, clear, fetchConfig, setGetToken } =
    useChat("/api");
  const { getToken, signOut } = useAuth();
  const { user } = useUser();

  useEffect(() => {
    setGetToken(() => getToken());
  }, [getToken, setGetToken]);

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
      onSignOut={() => signOut()}
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

  return (
    <div className="flex h-dvh w-full flex-col">
      <main className="flex flex-1 flex-col items-center justify-center px-4">
        <div className="w-full max-w-md space-y-8">
          <div className="text-center">
            <h1 className="text-foreground text-3xl font-medium tracking-tight">
              Welcome to Cycls
            </h1>
            <p className="text-muted-foreground mt-3">
              Sign in to get started.
            </p>
          </div>
          {error && (
            <div className="rounded-md bg-red-500/10 p-3 text-sm text-red-500">
              {error}
            </div>
          )}
          <div>
            <button
              onClick={handleGoogle}
              disabled={isLoading}
              className="flex w-full items-center justify-center gap-2 rounded-lg border border-border bg-secondary px-4 py-3 text-foreground font-medium hover:bg-secondary/80 transition-colors disabled:opacity-50 cursor-pointer"
            >
              <svg className="size-4" viewBox="0 0 24 24">
                <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" />
                <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
                <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
              </svg>
              {isLoading ? "Connecting..." : "Continue with Google"}
            </button>
          </div>
        </div>
      </main>
    </div>
  );
}

export default function App() {
  // If no Clerk key, skip auth entirely
  if (!CLERK_KEY) {
    return <ChatNoAuth />;
  }

  if (window.location.pathname === "/sso-callback") {
    return (
      <ClerkProvider publishableKey={CLERK_KEY}>
        <AuthenticateWithRedirectCallback />
      </ClerkProvider>
    );
  }

  return (
    <ClerkProvider publishableKey={CLERK_KEY}>
      <SignedIn>
        <ChatWithAuth />
      </SignedIn>
      <SignedOut>
        <CustomSignIn />
      </SignedOut>
    </ClerkProvider>
  );
}
