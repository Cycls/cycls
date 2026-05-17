import { useEffect, useState } from "react";
import { MessageBubble } from "./message";
import { CyclsLogo } from "./cycls-logo";
import { IconButton } from "./icon";
import type { Message } from "../hooks/use-chat";
import { track } from "../lib/posthog";
import { toggleDark } from "../lib/utils";

interface ChatShare {
  type: "chat";
  id: string;
  title: string;
  author_name?: string;
  author_image_url?: string;
  author_org_name?: string;
  author_org_image_url?: string;
  shared_at?: string;
  messages: Message[];
}

// File shares redirect to the raw URL — no SPA chrome, browser handles rendering.
interface FileShare { type: "file"; url: string }

export function SharedView({ getToken }: { getToken?: () => Promise<string | null> } = {}) {
  const [data, setData] = useState<ChatShare | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // /shared/<user>/<token> is the SPA route; JSON lives at /share/<user>/<token>/data.
    // Org-scoped shares need the viewer's bearer so the backend can match `audience: "org:<id>"`
    // against the requester's org_id. Public shares ignore the bearer.
    (async () => {
      try {
        const headers: Record<string, string> = {};
        if (getToken) {
          const token = await getToken();
          if (token) headers.Authorization = `Bearer ${token}`;
        }
        const res = await fetch(
          `${window.location.pathname.replace("/shared/", "/share/")}/data`,
          { headers },
        );
        if (res.status === 403) throw new Error("This share is private or expired");
        if (!res.ok) throw new Error("Share not found");
        const d = (await res.json()) as ChatShare | FileShare;
        if (d.type === "file") {
          // Browser redirects drop the Authorization header, so org file shares
          // would 403. Fetch with our bearer and hand the browser a blob URL.
          const fileRes = await fetch(d.url, { headers });
          if (!fileRes.ok) throw new Error("This share is private or expired");
          window.location.replace(URL.createObjectURL(await fileRes.blob()));
          return;
        }
        setData(d);
        document.title = d.title ? `Cycls | ${d.title}` : "Cycls";
        track("share_viewed", {
          chat_id: d.id,
          share_url: window.location.href,
          title: d.title,
          author_name: d.author_name,
          org_name: d.author_org_name,
          message_count: d.messages?.length || 0,
          referrer: document.referrer || null,
        });
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setError(msg);
        track("share_view_failed", { share_url: window.location.href, error: msg });
      } finally {
        setLoading(false);
      }
    })();
  }, [getToken]);

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
        <IconButton name="moon" onClick={() => toggleDark("shared_view")} label="Toggle theme" />
        </div>
      </header>

      <div className="shrink-0 h-12" />

      <div className="relative flex-1 overflow-y-auto scrollbar-none">
        <div className="pointer-events-none sticky top-0 z-10 h-6 -mb-6 bg-[linear-gradient(to_bottom,var(--color-background)_0%,var(--color-background)_20%,transparent_100%)]" />
        <div className="flex w-full flex-col items-center py-4">
          <ShareChrome
            title={data.title}
            authorName={data.author_name}
            authorImageUrl={data.author_image_url}
            authorOrgName={data.author_org_name}
            authorOrgImageUrl={data.author_org_image_url}
            sharedAt={data.shared_at}
          />
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


function ShareChrome({
  title,
  authorName,
  authorImageUrl,
  authorOrgName,
  authorOrgImageUrl,
  sharedAt,
}: {
  title?: string;
  authorName?: string;
  authorImageUrl?: string;
  authorOrgName?: string;
  authorOrgImageUrl?: string;
  sharedAt?: string;
}) {
  const hasAuthor = !!(authorName || authorImageUrl || authorOrgName || authorOrgImageUrl);
  if (!title && !hasAuthor && !sharedAt) return null;
  return (
    <div className="w-full max-w-3xl px-6 py-10 text-center">
      {title && <h1 className="text-xl font-medium tracking-tight text-foreground">{title}</h1>}
      <div className="flex items-center justify-center gap-2 mt-3">
        {hasAuthor && (
          <div className="flex items-center -space-x-3">
            {authorOrgImageUrl && (
              <div className="relative group">
                <div
                  className="size-6 rounded-full bg-secondary shrink-0 ring-2 ring-background"
                  style={{ backgroundImage: `url(${authorOrgImageUrl})`, backgroundSize: "cover" }}
                />
                {authorOrgName && (
                  <div className="pointer-events-none absolute left-1/2 top-full -translate-x-1/2 mt-1 opacity-0 group-hover:opacity-100 transition-opacity delay-300 z-50">
                    <div className="rounded-lg border border-border bg-background px-3 py-2 shadow-lg text-xs whitespace-nowrap">
                      <p className="font-medium text-foreground">{authorOrgName}</p>
                    </div>
                  </div>
                )}
              </div>
            )}
            {authorImageUrl && (
              <div className="relative group">
                <div
                  className="size-6 rounded-full bg-secondary shrink-0 ring-2 ring-background"
                  style={{ backgroundImage: `url(${authorImageUrl})`, backgroundSize: "cover" }}
                />
                {authorName && (
                  <div className="pointer-events-none absolute left-1/2 top-full -translate-x-1/2 mt-1 opacity-0 group-hover:opacity-100 transition-opacity delay-300 z-50">
                    <div className="rounded-lg border border-border bg-background px-3 py-2 shadow-lg text-xs whitespace-nowrap">
                      <p className="font-medium text-foreground">{authorName}</p>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
        {hasAuthor && <span className="text-xs text-muted-foreground">·</span>}
        {sharedAt && (
          <span className="text-xs text-muted-foreground">
            {new Date(sharedAt).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
          </span>
        )}
      </div>
    </div>
  );
}
