import { useState, useRef, useEffect, useCallback } from "react";
import { useStickToBottom } from "use-stick-to-bottom";
import { MessageBubble } from "./message";
import type { Message } from "../hooks/use-chat";

interface UserInfo {
  name: string;
  email: string;
  imageUrl?: string;
}

export function Chat({
  messages,
  isStreaming,
  onSend,
  onStop,
  onClear,
  onSignOut,
  onManageAccount,
  onCreateOrg,
  onManageOrg,
  onSwitchOrg,
  activeOrg,
  orgs,
  plan,
  title,
  user,
}: {
  messages: Message[];
  isStreaming: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
  onClear: () => void;
  onSignOut?: () => void;
  onManageAccount?: () => void;
  onCreateOrg?: () => void;
  onManageOrg?: () => void;
  onSwitchOrg?: (orgId: string | null) => void;
  activeOrg?: { id: string; name: string; imageUrl?: string };
  orgs?: { id: string; name: string; imageUrl: string }[];
  plan?: string;
  title?: string;
  user?: UserInfo;
}) {
  const [input, setInput] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { scrollRef, contentRef } = useStickToBottom();

  // Auto-resize textarea
  useEffect(() => {
    if (!textareaRef.current) return;
    textareaRef.current.style.height = "auto";
    textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`;
  }, [input]);

  // Focus on mount
  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  const handleSubmit = useCallback(() => {
    const text = input.trim();
    if (!text || isStreaming) return;
    setInput("");
    onSend(text);
  }, [input, isStreaming, onSend]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    const isMobile = window.matchMedia("(pointer: coarse)").matches;
    if (e.key === "Enter" && !e.shiftKey && !isMobile) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const toggleDark = () => {
    document.body.classList.toggle("dark");
  };

  return (
    <div className="h-dvh flex flex-col">
      {/* Header */}
      <header className="pointer-events-none fixed top-0 right-0 left-0 z-50 h-12">
        <div className="pointer-events-auto mx-auto flex h-full max-w-full items-center justify-between px-4 sm:px-6">
          <a href="/" className="flex items-center gap-2 text-foreground hover:opacity-80 transition-opacity">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 83.652 29" className="h-5 fill-muted-foreground">
              <path d="M 17.743 0.755 L 16.261 0.755 C 15.861 0.755 15.484 0.961 15.253 1.301 L 3.23 19.531 C 3.133 19.689 3.242 19.895 3.424 19.895 L 4.906 19.895 C 5.307 19.895 5.683 19.689 5.914 19.349 L 17.937 1.119 C 18.047 0.973 17.925 0.755 17.743 0.755 Z" />
              <path d="M 5.248 0 L 5.734 1.654 C 6.164 3.153 7.345 4.33 8.844 4.765 L 10.496 5.241 L 8.844 5.718 C 7.345 6.152 6.164 7.329 5.734 8.829 L 5.248 10.496 L 4.762 8.843 C 4.332 7.343 3.152 6.166 1.652 5.732 L 0 5.255 L 1.652 4.779 C 3.152 4.344 4.332 3.167 4.762 1.668 L 5.248 0 Z" />
              <path d="M 17.359 13.159 C 17.493 13.671 18.909 15.02 19.38 15.192 C 18.909 15.31 17.516 16.704 17.359 17.226 C 17.225 16.714 15.89 15.308 15.338 15.192 C 15.89 14.962 17.211 13.671 17.359 13.159 Z M 17.345 9.86 L 16.852 11.552 C 16.415 13.073 15.218 14.268 13.696 14.709 L 12.02 15.192 L 13.696 15.676 C 15.218 16.116 16.415 17.311 16.852 18.832 L 17.345 20.51 L 17.838 18.818 C 18.275 17.297 19.472 16.102 20.994 15.661 L 22.67 15.178 L 20.994 14.694 C 19.472 14.254 18.275 13.059 17.838 11.538 Z M 34.301 6.3 C 36.386 5.965 38.638 6.177 40.489 7.281 C 42.005 8.139 43.197 9.544 43.766 11.194 C 43.911 11.662 44.123 12.142 44.089 12.632 C 43.944 12.833 43.666 12.81 43.454 12.821 C 42.908 12.81 42.361 12.844 41.826 12.81 C 41.469 12.81 41.369 12.431 41.28 12.153 C 40.912 10.848 39.931 9.745 38.716 9.176 C 37.233 8.485 35.505 8.452 33.956 8.942 C 32.094 9.533 30.656 11.172 30.21 13.067 C 29.931 14.215 29.931 15.419 30.154 16.578 C 30.522 18.418 31.793 20.068 33.543 20.781 C 35.071 21.394 36.821 21.439 38.359 20.848 C 39.597 20.369 40.656 19.388 41.135 18.139 C 41.258 17.838 41.302 17.504 41.492 17.225 C 41.659 17.013 41.96 17.069 42.194 17.058 C 42.74 17.069 43.287 17.035 43.822 17.08 C 44.011 17.102 44.145 17.281 44.1 17.47 C 43.788 19.142 42.93 20.725 41.614 21.807 C 40.277 22.933 38.56 23.59 36.821 23.691 C 34.903 23.836 32.908 23.468 31.28 22.409 C 29.608 21.327 28.304 19.666 27.713 17.76 C 27.312 16.467 27.211 15.096 27.379 13.758 C 27.713 10.113 30.667 6.88 34.301 6.3 Z M 70.142 6.958 C 70.12 6.735 70.22 6.434 70.488 6.434 C 71.123 6.411 71.759 6.423 72.405 6.434 C 72.528 6.579 72.628 6.757 72.606 6.958 L 72.606 22.888 C 72.628 23.133 72.539 23.445 72.249 23.445 C 71.647 23.456 71.034 23.479 70.432 23.434 C 70.12 23.367 70.142 22.999 70.142 22.765 Z M 62.573 11.807 C 63.933 11.695 65.371 11.852 66.563 12.554 C 67.767 13.234 68.693 14.438 68.949 15.809 C 68.994 16.021 68.96 16.366 68.682 16.366 C 68.068 16.411 67.455 16.389 66.853 16.378 C 66.519 16.389 66.419 16.032 66.307 15.787 C 65.984 14.917 65.181 14.282 64.289 14.092 C 63.375 13.892 62.372 13.981 61.569 14.471 C 60.7 14.984 60.142 15.92 59.975 16.89 C 59.774 18.072 59.975 19.399 60.789 20.335 C 62.071 21.885 64.902 21.896 66.051 20.19 C 66.318 19.856 66.307 19.276 66.753 19.109 C 67.333 19.064 67.912 19.086 68.492 19.086 C 68.693 19.075 68.994 19.22 68.96 19.466 C 68.693 21.651 66.708 23.334 64.579 23.624 C 62.996 23.88 61.257 23.657 59.908 22.732 C 58.671 21.885 57.779 20.547 57.511 19.064 C 57.155 17.214 57.523 15.151 58.816 13.724 C 59.752 12.621 61.134 11.941 62.573 11.807 Z M 74.646 13 C 75.649 12.03 77.121 11.762 78.47 11.774 C 79.64 11.74 80.877 11.896 81.903 12.498 C 82.851 13.056 83.464 14.104 83.52 15.196 C 83.542 15.363 83.397 15.464 83.308 15.575 C 82.672 15.553 82.026 15.597 81.39 15.553 C 80.978 15.352 81.045 14.806 80.755 14.505 C 80.209 13.825 79.261 13.736 78.458 13.725 C 77.767 13.769 76.987 13.814 76.474 14.338 C 76.14 14.672 76.117 15.196 76.218 15.631 C 76.586 16.322 77.455 16.4 78.146 16.534 C 79.54 16.79 81.045 16.779 82.293 17.537 C 83.174 18.05 83.709 19.087 83.642 20.101 C 83.731 21.138 83.23 22.175 82.394 22.777 C 81.335 23.546 79.986 23.702 78.715 23.735 C 77.533 23.68 76.285 23.579 75.248 22.933 C 74.423 22.442 73.877 21.55 73.709 20.614 C 73.665 20.346 73.899 20.112 74.166 20.146 C 74.735 20.146 75.315 20.123 75.883 20.157 C 76.218 20.279 76.262 20.703 76.463 20.959 C 76.898 21.528 77.645 21.74 78.325 21.751 C 79.094 21.773 79.919 21.818 80.599 21.394 C 81.335 20.982 81.502 19.8 80.777 19.287 C 80.119 18.875 79.306 18.808 78.559 18.708 C 77.321 18.496 75.984 18.451 74.913 17.715 C 73.386 16.701 73.33 14.226 74.646 13 Z M 45.383 12.52 C 45.36 12.297 45.494 12.041 45.739 12.041 C 46.241 12.008 46.754 12.03 47.267 12.03 C 47.579 11.974 47.902 12.175 47.857 12.52 C 47.88 14.46 47.835 16.4 47.88 18.34 C 47.891 19.254 48.158 20.268 48.95 20.803 C 50.366 21.673 52.484 21.216 53.309 19.744 C 53.677 19.131 53.733 18.407 53.744 17.715 L 53.744 12.777 C 53.744 12.576 53.744 12.353 53.833 12.164 C 54.045 11.997 54.323 12.052 54.58 12.041 C 55.037 12.052 55.494 12.008 55.94 12.075 C 56.196 12.142 56.207 12.442 56.207 12.654 L 56.207 23.289 C 56.23 24.426 56.085 25.608 55.494 26.6 C 54.803 27.804 53.521 28.596 52.172 28.841 C 50.711 29.12 49.151 29.053 47.768 28.473 C 46.509 27.949 45.505 26.79 45.293 25.419 C 45.171 25.151 45.461 24.917 45.706 24.928 C 46.263 24.928 46.821 24.906 47.378 24.939 C 47.835 25.118 47.824 25.708 48.147 26.021 C 48.883 26.857 50.121 26.935 51.157 26.823 C 52.116 26.779 53.086 26.244 53.465 25.329 C 53.989 24.092 53.733 22.721 53.788 21.417 C 53.264 22.364 52.339 23.044 51.28 23.289 C 50.076 23.568 48.749 23.535 47.623 23 C 46.542 22.476 45.784 21.405 45.528 20.235 C 45.316 19.41 45.372 18.552 45.36 17.704 C 45.383 15.976 45.372 14.248 45.383 12.52 Z" />
            </svg>
            {title && <span className="text-sm font-semibold">{title}</span>}
          </a>
          <div className="flex items-center gap-1">
            {messages.length > 0 && (
              <button
                onClick={onClear}
                className="text-muted-foreground hover:text-foreground hover:bg-secondary/80 rounded-lg p-2 transition-colors cursor-pointer"
                aria-label="New chat"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
              </button>
            )}
            <button
              onClick={toggleDark}
              className="text-muted-foreground hover:text-foreground hover:bg-secondary/80 rounded-lg p-2 transition-colors cursor-pointer"
              aria-label="Toggle theme"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
              </svg>
            </button>
            {user && <div className="ml-1"><UserMenu user={user} onSignOut={onSignOut} onManageAccount={onManageAccount} onCreateOrg={onCreateOrg} onManageOrg={onManageOrg} onSwitchOrg={onSwitchOrg} activeOrg={activeOrg} orgs={orgs} plan={plan} /></div>}
          </div>
        </div>
      </header>

      {/* Spacer for fixed header */}
      <div className="shrink-0 h-12" />

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        <div ref={contentRef} className="flex w-full flex-col items-center py-4">
          {messages.length === 0 && (
            <div className="flex-1 flex items-center justify-center pt-32">
              <p className="text-muted-foreground">
                Send a message to get started
              </p>
            </div>
          )}
          {messages.map((msg, i) => (
            <MessageBubble
              key={i}
              message={msg}
              isStreaming={
                isStreaming &&
                i === messages.length - 1 &&
                msg.role === "assistant"
              }
            />
          ))}
        </div>
      </div>

      {/* Input */}
      <div className="shrink-0 px-6 pb-4 pt-2">
        <div className="max-w-3xl mx-auto">
          <div
            className="border border-border bg-background rounded-3xl p-2 shadow-sm cursor-text"
            onClick={() => textareaRef.current?.focus()}
          >
            <div className="flex items-end gap-2">
              <textarea
                ref={textareaRef}
                dir="auto"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Send a message..."
                rows={1}
                className="flex-1 min-h-[44px] max-h-[240px] resize-none bg-transparent px-3 py-2.5 text-foreground placeholder:text-muted-foreground focus:outline-none overflow-y-auto"
              />
              <div className="flex items-center pb-1 pr-1">
                {isStreaming ? (
                  <button
                    type="button"
                    onClick={onStop}
                    className="flex size-9 items-center justify-center rounded-full bg-foreground text-background hover:opacity-80 transition cursor-pointer"
                    aria-label="Stop"
                  >
                    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
                      <rect x="6" y="6" width="12" height="12" rx="2" />
                    </svg>
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); handleSubmit(); }}
                    disabled={!input.trim()}
                    className="flex size-9 items-center justify-center rounded-full bg-foreground text-background hover:opacity-80 disabled:opacity-30 transition cursor-pointer"
                    aria-label="Send"
                  >
                    <svg
                      className="w-4 h-4"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M5 12h14M12 5l7 7-7 7"
                      />
                    </svg>
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function UserMenu({ user, onSignOut, onManageAccount, onCreateOrg, onManageOrg, onSwitchOrg, activeOrg, orgs, plan }: {
  user: UserInfo;
  onSignOut?: () => void;
  onManageAccount?: () => void;
  onCreateOrg?: () => void;
  onManageOrg?: () => void;
  onSwitchOrg?: (orgId: string | null) => void;
  activeOrg?: { id: string; name: string; imageUrl?: string };
  orgs?: { id: string; name: string; imageUrl: string }[];
  plan?: string;
}) {
  const [open, setOpen] = useState(false);
  const [showOrgs, setShowOrgs] = useState(false);

  return (
    <div className="relative">
      <button
        onClick={() => { setOpen(!open); setShowOrgs(false); }}
        className="flex size-8 items-center justify-center rounded-lg hover:opacity-80 transition-opacity cursor-pointer"
        aria-label="Profile"
      >
        <div
          className="size-6 rounded-full bg-secondary text-foreground flex items-center justify-center text-xs font-medium select-none"
          style={user.imageUrl ? { backgroundImage: `url(${user.imageUrl})`, backgroundSize: "cover" } : undefined}
        >
          {!user.imageUrl && (user.name?.charAt(0) || user.email?.charAt(0) || "?")}
        </div>
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => { setOpen(false); setShowOrgs(false); }} />
          <div className="absolute right-0 top-full z-50 mt-2 w-56 rounded-lg border border-border bg-background shadow-lg">
            {showOrgs ? (
              <>
                <button
                  onClick={() => setShowOrgs(false)}
                  className="flex w-full items-center gap-2 px-3 py-2.5 text-sm text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
                >
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                  </svg>
                  Back
                </button>
                <div className="border-t border-border" />
                <div className="py-1">
                  <button
                    onClick={() => { onSwitchOrg?.(null); setShowOrgs(false); }}
                    className={`flex w-full items-center gap-2 px-3 py-1.5 text-sm transition-colors cursor-pointer ${!activeOrg ? "text-foreground bg-secondary/60" : "text-muted-foreground hover:text-foreground hover:bg-secondary/80"}`}
                  >
                    Personal
                  </button>
                  {(orgs || []).map((org) => (
                    <button
                      key={org.id}
                      onClick={() => { onSwitchOrg?.(org.id); setShowOrgs(false); }}
                      className={`flex w-full items-center gap-2 px-3 py-1.5 text-sm transition-colors cursor-pointer ${activeOrg?.id === org.id ? "text-foreground bg-secondary/60" : "text-muted-foreground hover:text-foreground hover:bg-secondary/80"}`}
                    >
                      {org.name}
                    </button>
                  ))}
                </div>
                {onCreateOrg && (
                  <>
                    <div className="border-t border-border" />
                    <button
                      onClick={() => { setOpen(false); setShowOrgs(false); onCreateOrg(); }}
                      className="flex w-full items-center gap-2 px-3 py-2.5 text-sm text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
                    >
                      Create organization
                    </button>
                  </>
                )}
              </>
            ) : (
              <>
                <div className="px-3 py-2.5">
                  <p className="text-sm font-medium text-foreground truncate">{user.name}</p>
                  <p className="text-xs text-muted-foreground truncate">{user.email}</p>
                  {plan && (
                    <span className="inline-block mt-1.5 rounded-full bg-secondary px-2 py-0.5 text-[11px] text-muted-foreground">{plan}</span>
                  )}
                </div>
                <div className="border-t border-border" />
                {onSwitchOrg && (
                  <button
                    onClick={() => setShowOrgs(true)}
                    className="flex w-full items-center justify-between px-3 py-2.5 text-sm text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
                  >
                    <span className="flex items-center gap-2 truncate">
                      {activeOrg?.imageUrl && (
                        <div className="size-4 rounded-full shrink-0" style={{ backgroundImage: `url(${activeOrg.imageUrl})`, backgroundSize: "cover" }} />
                      )}
                      {activeOrg ? activeOrg.name : "Personal"}<span className="text-muted-foreground font-normal"> · org</span>
                    </span>
                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                    </svg>
                  </button>
                )}
                {onManageAccount && (
                  <button
                    onClick={() => { setOpen(false); onManageAccount(); }}
                    className="flex w-full items-center gap-2 px-3 py-2.5 text-sm text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
                  >
                    Account
                  </button>
                )}
                {onManageOrg && activeOrg && (
                  <button
                    onClick={() => { setOpen(false); onManageOrg(); }}
                    className="flex w-full items-center gap-2 px-3 py-2.5 text-sm text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
                  >
                    Manage organization
                  </button>
                )}
                {onSignOut && (
                  <>
                    <div className="border-t border-border" />
                    <button
                      onClick={() => { setOpen(false); onSignOut(); }}
                      className="flex w-full items-center gap-2 px-3 py-2.5 text-sm text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
                    >
                      Sign out
                    </button>
                  </>
                )}
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}
