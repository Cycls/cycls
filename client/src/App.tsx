import { useEffect } from "react";
import {
  ClerkProvider,
  SignedIn,
  SignedOut,
  SignIn,
  useAuth,
} from "@clerk/clerk-react";
import { Chat } from "./components/chat";
import { useChat } from "./hooks/use-chat";

const CLERK_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY;

function ChatWithAuth() {
  const { messages, isStreaming, config, send, stop, clear, fetchConfig, setGetToken } =
    useChat("/api");
  const { getToken } = useAuth();

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
      title={config?.header}
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

export default function App() {
  // If no Clerk key, skip auth entirely
  if (!CLERK_KEY) {
    return <ChatNoAuth />;
  }

  return (
    <ClerkProvider publishableKey={CLERK_KEY}>
      <SignedIn>
        <ChatWithAuth />
      </SignedIn>
      <SignedOut>
        <div className="min-h-screen flex items-center justify-center">
          <SignIn />
        </div>
      </SignedOut>
    </ClerkProvider>
  );
}
