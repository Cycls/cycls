import { useEffect, useState, useCallback, useMemo } from "react";
import { MessageBubble } from "./message";
import { CyclsLogo } from "./cycls-logo";
import { Icon, IconButton } from "./icon";
import { useFileContent, CanvasDoc, type CanvasFile } from "./canvas";
import { isRenderable, saveBlob } from "./canvas-utils";
import type { Message } from "../hooks/use-chat";
import { track } from "../lib/posthog";
import { toggleDark } from "../lib/utils";

interface Author {
  author_name?: string;
  author_image_url?: string;
  author_org_name?: string;
  author_org_image_url?: string;
  shared_at?: string;
}

interface ChatShare extends Author {
  type: "chat";
  id: string;
  title: string;
  messages: Message[];
}

interface FileShare extends Author {
  type: "file";
  path: string;
  url: string;
}

export function SharedView({ getToken }: { getToken?: () => Promise<string | null> } = {}) {
  const [data, setData] = useState<ChatShare | FileShare | null>(null);
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
          // Keep the query: `?ws=` names the workspace that minted the share.
          `${window.location.pathname.replace("/shared/", "/share/")}/data${window.location.search}`,
          { headers },
        );
        if (res.status === 403) throw new Error("This share is private or expired");
        if (!res.ok) throw new Error("Share not found");
        const d = (await res.json()) as ChatShare | FileShare;
        setData(d);
        if (d.type === "chat") {
          document.title = d.title ? `Cycls | ${d.title}` : "Cycls";
        } else {
          document.title = `Cycls | ${d.path.split("/").pop()}`;
        }
        track("share_viewed", {
          type: d.type,
          chat_id: d.type === "chat" ? d.id : undefined,
          file: d.type === "file" ? d.path : undefined,
          share_url: window.location.href,
          author_name: d.author_name,
          org_name: d.author_org_name,
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
  if (data.type === "file") return <SharedFile share={data} getToken={getToken} />;

  return (
    <div className="h-dvh flex flex-col bg-background">
      <ShareHeader />
      <div className="shrink-0 h-12" />

      <div className="relative flex-1 overflow-y-auto scrollbar-none">
        <div className="pointer-events-none sticky top-0 z-10 h-6 -mb-6 bg-[linear-gradient(to_bottom,var(--color-background)_0%,var(--color-background)_20%,transparent_100%)]" />
        <div className="flex w-full flex-col items-center py-4">
          <ShareChrome {...data} />
          {data.messages.map((msg, i) => (
            <MessageBubble key={i} message={msg} isStreaming={false} />
          ))}
          <button
            onClick={() => {
              // Carry `?ws=` inside the fork param; forkShare() splits it back out.
              const userToken = window.location.pathname.replace(/^\/shared\//, "") + window.location.search;
              window.location.href = `/?fork=${encodeURIComponent(userToken)}`;
            }}
            className="mt-6 text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
          >
            Continue this conversation →
          </button>
          <ShareFooter />
        </div>
      </div>
    </div>
  );
}

// File share — render through the same canvas viewer the owner sees, but
// read-only and over the token-scoped /share/.../file/ transport (public =
// no bearer; org = viewer's bearer). Unrenderable types (docx/xlsx/zip) get a
// name-preserving download instead of a corrupt blob.
function SharedFile({ share, getToken }: { share: FileShare; getToken?: () => Promise<string | null> }) {
  const name = share.path.split("/").pop() || share.path;
  const file = useMemo<CanvasFile>(() => ({ path: share.path, name }), [share.path, name]);
  const renderable = isRenderable(name);
  const shareBase = window.location.pathname.replace("/shared/", "/share/");  // /share/{user}/{token}

  const authedFetch = useCallback(async (p: string) => {
    const headers: Record<string, string> = {};
    if (getToken) { const tk = await getToken(); if (tk) headers.Authorization = `Bearer ${tk}`; }
    const res = await fetch(`${shareBase}/file/${p}`, { headers });
    if (!res.ok) throw new Error("This share is private or expired");
    return res;
  }, [getToken, shareBase]);

  const readFile = useCallback(async (p: string) => (await authedFetch(p)).text(), [authedFetch]);
  const openFile = useCallback(async (p: string) => URL.createObjectURL(await (await authedFetch(p)).blob()), [authedFetch]);

  // Fetch only renderable files; unrenderable just offer download.
  const { content, error } = useFileContent(renderable ? file : null, readFile, openFile);
  const download = () => openFile(share.path).then((url) => saveBlob(url, name)).catch(() => {});

  return (
    <div className="h-dvh flex flex-col bg-background">
      <ShareHeader />
      <div className="shrink-0 h-12" />

      <div className="flex-1 min-h-0 flex flex-col px-2 pb-2 sm:px-3 sm:pb-3">
        <div className="flex-1 min-h-0 flex flex-col rounded-xl border border-border overflow-hidden">
          <div className="flex items-center gap-2 border-b border-border px-4 sm:px-6 py-3">
            <span className="min-w-0 truncate text-sm font-medium text-foreground">{name}</span>
            <div className="flex-1" />
            <button
              onClick={download}
              className="flex size-8 items-center justify-center rounded-lg text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
              aria-label="Download"
              title="Download"
            >
              <svg className="size-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
              </svg>
            </button>
          </div>
          <div className="flex-1 overflow-hidden">
            {renderable ? (
              <CanvasDoc file={file} content={content} error={error} shared />
            ) : (
              <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
                <Icon name="folder" className="size-10 text-muted-foreground/40" strokeWidth={1.5} />
                <p className="text-sm text-foreground">{name}</p>
                <p className="text-xs text-muted-foreground">Preview isn't available for this file type.</p>
                <button
                  onClick={download}
                  className="mt-1 rounded-lg bg-secondary px-4 py-2 text-sm font-medium text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
                >
                  Download {name}
                </button>
              </div>
            )}
          </div>
        </div>
        <div className="shrink-0"><ShareFooter /></div>
      </div>
    </div>
  );
}

function ShareHeader() {
  return (
    <header className="pointer-events-none fixed top-0 right-0 left-0 z-50 h-12">
      <div className="pointer-events-auto mx-auto flex h-full max-w-full items-center justify-between px-4 sm:px-6">
        <a href="https://cycls.ai" className="flex items-center gap-2 text-foreground hover:opacity-80 transition-opacity">
          <CyclsLogo className="h-5 fill-muted-foreground" />
        </a>
        <div className="flex-1" />
        <IconButton name="moon" onClick={() => toggleDark("shared_view")} label="Toggle theme" />
      </div>
    </header>
  );
}

function ShareFooter() {
  return (
    <div className="w-full max-w-3xl mx-auto px-6 pt-8 pb-10">
      <div className="flex justify-center">
        <a href="https://cycls.ai" className="flex items-center gap-1 text-muted-foreground hover:text-foreground transition-colors">
          <span className="text-[10px]">Made in</span>
          <CyclsLogo className="h-[13px] fill-current" />
        </a>
      </div>
    </div>
  );
}

function ShareChrome({
  title,
  author_name: authorName,
  author_image_url: authorImageUrl,
  author_org_name: authorOrgName,
  author_org_image_url: authorOrgImageUrl,
  shared_at: sharedAt,
}: Author & { title?: string }) {
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
