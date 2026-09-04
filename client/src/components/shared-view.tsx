import { useEffect, useState, useCallback, useMemo } from "react";
import { MessageBubble } from "./message";
import { CyclsLogo } from "./cycls-logo";
import { Icon, IconButton } from "./icon";
import { useFileContent, CanvasDoc, type CanvasFile } from "./canvas";
import { isHtml, isRenderable, saveBlob, extTint } from "./canvas-utils";
import type { Message } from "../hooks/use-chat";
import { useMediaQuery } from "../hooks/use-media-query";
import { t } from "../lib/i18n";
import { track } from "../lib/analytics";
import { toggleDark, cn } from "../lib/utils";

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

export function SharedView({ getToken, signedIn, onSignIn }: {
  getToken?: () => Promise<string | null>;
  signedIn?: boolean;
  onSignIn?: () => void;
} = {}) {
  const [data, setData] = useState<ChatShare | FileShare | null>(null);
  const [error, setError] = useState<{ message: string; signIn: boolean } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // /shared/<user>/<token> is the SPA route; JSON lives at /share/<user>/<token>/data.
    // Org-scoped shares need the viewer's bearer so the backend can match `audience: "org:<id>"`
    // against the requester's org_id. Public shares ignore the bearer.
    // Re-runs when the viewer signs in, so a 401 recovers without a reload.
    let cancelled = false;
    setError(null);
    setLoading(true);
    (async () => {
      try {
        const headers: Record<string, string> = {};
        if (getToken) {
          const token = await getToken();
          if (token) headers.Authorization = `Bearer ${token}`;
        }
        const res = await fetch(
          `${window.location.pathname.replace("/shared/", "/share/")}/data${window.location.search}`,
          { headers },
        );
        // 401 is the recoverable one: the link is fine, we just don't know who
        // you are. 403 means we do, and it isn't for you.
        if (res.status === 401) throw new Error("SIGN_IN");
        if (res.status === 403) throw new Error("This link isn't shared with your account");
        if (res.status === 404) throw new Error("This link doesn't exist");
        if (!res.ok) throw new Error("Couldn't load this share");
        const d = (await res.json()) as ChatShare | FileShare;
        if (cancelled) return;
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
          // Gallery traffic (?example=1) vs organic user-to-user shares.
          example: new URLSearchParams(window.location.search).has("example"),
          artifacts: d.type === "chat" ? canvasArtifacts(d.messages).length : 1,
          signed_in: !!signedIn,
          share_url: window.location.href,
          author_name: d.author_name,
          org_name: d.author_org_name,
          referrer: document.referrer || null,
        });
      } catch (err) {
        if (cancelled) return;
        const msg = err instanceof Error ? err.message : String(err);
        setError(msg === "SIGN_IN"
          ? { message: "Sign in to view this", signIn: true }
          : { message: msg, signIn: false });
        track("share_view_failed", { share_url: window.location.href, error: msg });
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [getToken, signedIn]);

  if (loading) {
    return (
      <div className="flex h-dvh items-center justify-center">
        <div className="text-muted-foreground text-sm">Loading...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-dvh flex-col items-center justify-center gap-3">
        <div className="text-muted-foreground text-sm">{error.message}</div>
        {error.signIn && onSignIn && (
          <button
            onClick={onSignIn}
            className="cursor-pointer rounded-lg bg-foreground px-3 py-1.5 text-sm font-medium text-background"
          >
            Sign in
          </button>
        )}
      </div>
    );
  }

  if (!data) return null;
  if (data.type === "file") return <SharedFile share={data} getToken={getToken} />;
  return <SharedChat share={data} getToken={getToken} />;
}

// Canvas artifacts the conversation produced, in order — same derivation the
// live chat uses for file cards (message.tsx groupKind).
export function canvasArtifacts(messages: Message[]) {
  const out: string[] = [];
  for (const m of messages)
    for (const p of m.parts || [])
      if (p.type === "step" && p.tool_name === "Canvas" && p.step && p.ok !== false && !out.includes(p.step))
        out.push(p.step);
  return out;
}

// Chat share — the conversation WITH its output: transcript beside the canvas,
// every artifact pre-opened as a tab (same strip as the owner's canvas), the
// final one active. A floating "continue" pill rides the scroll — the page's
// one conversion affordance is never out of sight.
function SharedChat({ share, getToken }: { share: ChatShare; getToken?: () => Promise<string | null> }) {
  const params = new URLSearchParams(window.location.search);
  // Curated example (?example=1): product showcase, not user content — no
  // author chrome. Regular shares keep their attribution.
  const isExample = params.has("example");
  const isDesktop = useMediaQuery("(min-width: 1024px)");
  const artifacts = useMemo(() => canvasArtifacts(share.messages), [share.messages]);
  const [tabs, setTabs] = useState<string[]>(artifacts);
  // ?open= deep-links a file (activates everywhere); otherwise the final
  // artifact is active on desktop, and mobile keeps the transcript first
  // (file cards open the pane).
  const [active, setActive] = useState<string | null>(() =>
    params.get("open")
    || (window.matchMedia("(min-width: 1024px)").matches ? artifacts[artifacts.length - 1] || null : null));

  const openFromCard = (p: string) => {
    setTabs((ts) => (ts.includes(p) ? ts : [...ts, p]));
    setActive(p);
  };
  // Browser-tab semantics: closing the active tab activates its neighbor;
  // closing the last one hides the pane (cards in the transcript reopen it).
  const closeTab = (p: string) => {
    setTabs((ts) => {
      const rest = ts.filter((x) => x !== p);
      setActive((a) => (a === p ? rest[rest.length - 1] ?? null : a));
      return rest;
    });
  };

  const fork = () => {
    const userToken = window.location.pathname.replace(/^\/shared\//, "") + window.location.search;
    track("share_fork_clicked", { share_url: window.location.href, example: isExample });
    window.location.href = `/?fork=${encodeURIComponent(userToken)}`;
  };

  const pane = active && (
    <SharedCanvas
      tabs={tabs}
      active={active}
      getToken={getToken}
      onSelectTab={setActive}
      onCloseTab={closeTab}
      onClose={() => setActive(null)}
    />
  );

  return (
    <div className="h-dvh flex flex-col bg-background">
      <ShareHeader />
      <div className="shrink-0 h-12" />

      <div className="flex min-h-0 flex-1">
        <div className="relative flex h-full min-w-0 flex-1 flex-col">
          <div className="relative flex-1 overflow-y-auto scrollbar-none">
            <div className="pointer-events-none sticky top-0 z-10 h-6 -mb-6 bg-[linear-gradient(to_bottom,var(--color-background)_0%,var(--color-background)_20%,transparent_100%)]" />
            <div className="flex w-full flex-col items-center py-4">
              <ShareChrome {...share} hideAuthor={isExample} />
              {share.messages.map((msg, i) => (
                <MessageBubble key={i} message={msg} isStreaming={false} onOpenFile={openFromCard} />
              ))}
              <ShareFooter />
            </div>
            <div className="pointer-events-none sticky bottom-6 z-20 flex justify-center">
              <button
                onClick={fork}
                className="pointer-events-auto rounded-full bg-foreground px-5 py-2.5 text-sm font-medium text-background shadow-lg hover:opacity-90 transition-opacity cursor-pointer"
              >
                {t("continueConversation")}
              </button>
            </div>
          </div>
        </div>

        {pane && (isDesktop ? (
          <div className="w-[52%] max-w-[880px] min-h-0 shrink-0 p-2 pl-0 sm:p-3 sm:pl-0">{pane}</div>
        ) : (
          <div className="fixed inset-0 z-40 bg-background p-2 pt-14">{pane}</div>
        ))}
      </div>
    </div>
  );
}

// Read-only canvas card over the token-scoped /share/.../file/ transport —
// the same viewer (and the same tab strip) the owner sees, minus the workspace.
function SharedCanvas({ tabs, active, getToken, onSelectTab, onCloseTab, onClose }: {
  tabs: string[];
  active: string;
  getToken?: () => Promise<string | null>;
  onSelectTab: (path: string) => void;
  onCloseTab: (path: string) => void;
  onClose: () => void;
}) {
  const path = active;
  const name = path.split("/").pop() || path;
  const file = useMemo<CanvasFile>(() => ({ path, name }), [path, name]);
  const renderable = isRenderable(name);
  const shareBase = window.location.pathname.replace("/shared/", "/share/");
  const shareQuery = window.location.search;   // carries ?ws= for team-minted shares

  const authedFetch = useCallback(async (p: string) => {
    const headers: Record<string, string> = {};
    if (getToken) { const tk = await getToken(); if (tk) headers.Authorization = `Bearer ${tk}`; }
    const res = await fetch(`${shareBase}/file/${p}${shareQuery}`, { headers });
    if (!res.ok) throw new Error("Couldn't load this file");
    return res;
  }, [getToken, shareBase, shareQuery]);
  const readFile = useCallback(async (p: string) => (await authedFetch(p)).text(), [authedFetch]);
  const openFile = useCallback(async (p: string) => URL.createObjectURL(await (await authedFetch(p)).blob()), [authedFetch]);

  const { content, error } = useFileContent(renderable ? file : null, readFile, openFile);
  const download = () => openFile(path).then((url) => saveBlob(url, name)).catch(() => {});
  const openInTab = () => {
    if (content == null) return;
    window.open(URL.createObjectURL(new Blob([content], { type: "text/html" })), "_blank");
  };

  return (
    <div className="flex h-full min-h-0 flex-col rounded-xl border border-border overflow-hidden bg-background">
      {/* Tab strip — same anatomy as the owner's canvas (canvas.tsx): one tab
          per artifact, tint dot, per-tab close revealed on hover. */}
      <div className="flex h-11 shrink-0 items-center gap-1 border-b border-border px-2">
        <div className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
          {tabs.map((p) => {
            const tabName = p.split("/").pop() || p;
            const on = p === path;
            const tint = extTint(tabName);
            return (
              <div
                key={p}
                role="button"
                onClick={() => onSelectTab(p)}
                className={cn(
                  "group flex min-w-20 max-w-44 flex-1 basis-0 cursor-pointer items-center gap-1.5 rounded-lg py-1 pl-2.5 pr-1 text-xs transition-colors",
                  on ? "bg-secondary text-foreground font-medium" : "text-muted-foreground hover:bg-secondary/50 hover:text-foreground",
                )}
              >
                {tint && <span className="size-1.5 rounded-full" style={{ backgroundColor: tint }} />}
                <span className="min-w-0 flex-1 truncate">{tabName}</span>
                <button
                  onClick={(e) => { e.stopPropagation(); onCloseTab(p); }}
                  className={cn("shrink-0 rounded p-0.5 hover:bg-accent/20", on ? "" : "opacity-0 group-hover:opacity-100")}
                  aria-label={`Close ${tabName}`}
                >
                  <Icon name="x" className="size-3" />
                </button>
              </div>
            );
          })}
        </div>
        {isHtml(name) && content != null && (
          <button
            onClick={openInTab}
            className="flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-secondary/80 hover:text-foreground cursor-pointer"
            aria-label="Open in new tab"
            title="Open in new tab"
          >
            <svg className="size-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-7.5 3L21 3m0 0h-5.25M21 3v5.25" />
            </svg>
          </button>
        )}
        <button
          onClick={download}
          className="flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-secondary/80 hover:text-foreground cursor-pointer"
          aria-label="Download"
          title="Download"
        >
          <svg className="size-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
          </svg>
        </button>
        <button
          onClick={onClose}
          className="flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-secondary/80 hover:text-foreground cursor-pointer"
          aria-label="Close"
          title="Close"
        >
          <Icon name="x" className="size-4" />
        </button>
      </div>
      <div className="flex-1 overflow-hidden">
        {renderable ? (
          <CanvasDoc file={file} content={content} error={error} shared />
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
            <Icon name="folder" className="size-10 text-muted-foreground/40" strokeWidth={1.5} />
            <p className="text-sm text-foreground">{name}</p>
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
  // `?ws=` names the workspace that minted the share — without it the server
  // has to guess, and a share from a team workspace isn't found at all.
  const shareBase = window.location.pathname.replace("/shared/", "/share/") ;  // /share/{user}/{token}
  const shareQuery = window.location.search;

  const authedFetch = useCallback(async (p: string) => {
    const headers: Record<string, string> = {};
    if (getToken) { const tk = await getToken(); if (tk) headers.Authorization = `Bearer ${tk}`; }
    const res = await fetch(`${shareBase}/file/${p}${shareQuery}`, { headers });
    if (!res.ok) throw new Error("Couldn't load this file");
    return res;
  }, [getToken, shareBase, shareQuery]);

  const readFile = useCallback(async (p: string) => (await authedFetch(p)).text(), [authedFetch]);
  const openFile = useCallback(async (p: string) => URL.createObjectURL(await (await authedFetch(p)).blob()), [authedFetch]);

  // Fetch only renderable files; unrenderable just offer download.
  const { content, error } = useFileContent(renderable ? file : null, readFile, openFile);
  const download = () => openFile(share.path).then((url) => saveBlob(url, name)).catch(() => {});

  // A shared page renders HTML in a sandboxed iframe sized to this layout; the
  // new tab gives it a full window and its own browsing context.
  const openInTab = () => {
    if (content == null) return;
    window.open(URL.createObjectURL(new Blob([content], { type: "text/html" })), "_blank");
  };

  return (
    <div className="h-dvh flex flex-col bg-background">
      <ShareHeader />
      <div className="shrink-0 h-12" />

      <div className="flex-1 min-h-0 flex flex-col px-2 pb-2 sm:px-3 sm:pb-3">
        <div className="flex-1 min-h-0 flex flex-col rounded-xl border border-border overflow-hidden">
          <div className="flex items-center gap-2 border-b border-border px-4 sm:px-6 py-3">
            <span className="min-w-0 truncate text-sm font-medium text-foreground">{name}</span>
            <div className="flex-1" />
            {isHtml(name) && content != null && (
              <button
                onClick={openInTab}
                className="flex items-center gap-1.5 rounded-lg px-2.5 h-8 text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
              >
                Open in new tab
                <svg className="size-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-7.5 3L21 3m0 0h-5.25M21 3v5.25" />
                </svg>
              </button>
            )}
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
  hideAuthor,
}: Author & { title?: string; hideAuthor?: boolean }) {
  // Curated examples show as product, not as someone's share.
  if (hideAuthor) {
    if (!title) return null;
    return (
      <div className="w-full max-w-3xl px-6 py-10 text-center">
        <h1 className="text-xl font-medium tracking-tight text-foreground">{title}</h1>
      </div>
    );
  }
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
