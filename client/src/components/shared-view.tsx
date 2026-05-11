import { useEffect, useState } from "react";
import { MessageBubble } from "./message";
import { CyclsLogo } from "./cycls-logo";
import type { Message } from "../hooks/use-chat";
import { track } from "../lib/posthog";
import { toggleDark } from "../lib/utils";

type Author = { name: string; imageUrl?: string; org?: { name: string; imageUrl?: string } };

interface ChatShare {
  type: "chat";
  id: string;
  title: string;
  author?: Author;
  shared_at?: string;
  messages: Message[];
}

// File shares redirect to the raw URL — no SPA chrome, browser handles rendering.
interface FileShare { type: "file"; url: string }

export function SharedView() {
  const [data, setData] = useState<ChatShare | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // /shared/<user>/<token> is the SPA route; JSON lives at /share/<user>/<token>/data.
    fetch(`${window.location.pathname.replace("/shared/", "/share/")}/data`)
      .then((res) => {
        if (res.status === 403) throw new Error("This share has expired");
        if (!res.ok) throw new Error("Share not found");
        return res.json() as Promise<ChatShare | FileShare>;
      })
      .then((d) => {
        if (d.type === "file") { window.location.replace(d.url); return; }
        setData(d);
        document.title = d.title ? `Cycls | ${d.title}` : "Cycls";
        track("share_viewed", {
          chat_id: d.id,
          share_url: window.location.href,
          title: d.title,
          author_name: d.author?.name,
          org_name: d.author?.org?.name,
          message_count: d.messages?.length || 0,
          referrer: document.referrer || null,
        });
      })
      .catch((err) => {
        setError(err.message);
        track("share_view_failed", {
          share_url: window.location.href,
          error: err.message,
        });
      })
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex h-dvh items-center justify-center">
        <div className="text-muted-foreground text-sm">Loading...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-dvh items-center justify-center">
        <div className="text-muted-foreground text-sm">{error}</div>
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="h-dvh flex flex-col bg-background">
      <header className="pointer-events-none fixed top-0 right-0 left-0 z-50 h-12">
        <div className="pointer-events-auto mx-auto flex h-full max-w-full items-center justify-between px-4 sm:px-6">
        <a href="https://cycls.ai" className="flex items-center gap-2 text-foreground hover:opacity-80 transition-opacity">
          <CyclsLogo className="h-5 fill-muted-foreground" />
        </a>
        <div className="flex-1" />
        <button
          onClick={() => toggleDark("shared_view")}
          className="text-muted-foreground hover:text-foreground hover:bg-secondary/80 rounded-lg p-2 transition-colors cursor-pointer"
          aria-label="Toggle theme"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
          </svg>
        </button>
        </div>
      </header>

      <div className="shrink-0 h-12" />

      <div className="relative flex-1 overflow-y-auto scrollbar-none">
        <div className="pointer-events-none sticky top-0 z-10 h-6 -mb-6 bg-[linear-gradient(to_bottom,var(--color-background)_0%,var(--color-background)_20%,transparent_100%)]" />
        <div className="flex w-full flex-col items-center py-4">
          <ShareChrome title={data.title} author={data.author} sharedAt={data.shared_at} />
          {data.messages.map((msg, i) => (
            <MessageBubble key={i} message={msg} isStreaming={false} />
          ))}
          <button
            onClick={() => {
              const userToken = window.location.pathname.replace(/^\/shared\//, "");
              window.location.href = `/?fork=${encodeURIComponent(userToken)}`;
            }}
            className="mt-6 text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
          >
            Continue this conversation →
          </button>

          {/* Footer */}
          <div className="w-full max-w-3xl px-6 pt-8 pb-10">
            <div className="flex justify-center">
              <a href="https://cycls.ai" className="flex items-center gap-1 text-muted-foreground hover:text-foreground transition-colors">
                <span className="text-[10px]">Made in</span>
                <CyclsLogo className="h-[13px] fill-current" />
              </a>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}


function ShareChrome({ title, author, sharedAt }: { title?: string; author?: Author; sharedAt?: string }) {
  if (!title && !author && !sharedAt) return null;
  return (
    <div className="w-full max-w-3xl px-6 py-10 text-center">
      {title && <h1 className="text-xl font-medium tracking-tight text-foreground">{title}</h1>}
      <div className="flex items-center justify-center gap-2 mt-3">
        {author && (
          <div className="flex items-center -space-x-3">
            {author.org?.imageUrl && (
              <div className="relative group">
                <div
                  className="size-6 rounded-full bg-secondary shrink-0 ring-2 ring-background"
                  style={{ backgroundImage: `url(${author.org.imageUrl})`, backgroundSize: "cover" }}
                />
                <div className="pointer-events-none absolute left-1/2 top-full -translate-x-1/2 mt-1 opacity-0 group-hover:opacity-100 transition-opacity delay-300 z-50">
                  <div className="rounded-lg border border-border bg-background px-3 py-2 shadow-lg text-xs whitespace-nowrap">
                    <p className="font-medium text-foreground">{author.org.name}</p>
                  </div>
                </div>
              </div>
            )}
            {author.imageUrl && (
              <div className="relative group">
                <div
                  className="size-6 rounded-full bg-secondary shrink-0 ring-2 ring-background"
                  style={{ backgroundImage: `url(${author.imageUrl})`, backgroundSize: "cover" }}
                />
                <div className="pointer-events-none absolute left-1/2 top-full -translate-x-1/2 mt-1 opacity-0 group-hover:opacity-100 transition-opacity delay-300 z-50">
                  <div className="rounded-lg border border-border bg-background px-3 py-2 shadow-lg text-xs whitespace-nowrap">
                    <p className="font-medium text-foreground">{author.name}</p>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
        {author && <span className="text-xs text-muted-foreground">·</span>}
        {sharedAt && (
          <span className="text-xs text-muted-foreground">
            {new Date(sharedAt).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
          </span>
        )}
      </div>
    </div>
  );
}
