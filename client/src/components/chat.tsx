import { useState, useRef, useEffect, useCallback } from "react";
import { motion, LayoutGroup, AnimatePresence } from "framer-motion";
import { useStickToBottom } from "use-stick-to-bottom";
import { MessageBubble } from "./message";
import { Files, InlineInput, DropdownMenu } from "./files";
import { Canvas, type CanvasFile } from "./canvas";
import { Popover } from "./popover";
import { Icon, IconButton } from "./icon";
import { CyclsLogo } from "./cycls-logo";
import { LoadingBar } from "./loading-bar";
import { InputBox } from "./input-box";
import { ShareDialog } from "./share-dialog";
import { PricingCards } from "./pricing-cards";
import { UserMenu, type UserInfo, type PlanInfo } from "./user-menu";
import { WorkspaceSwitcher, type WorkspacesMenu } from "./workspace-switcher";
import type { Attachment, ChatApi, AppConfig } from "../hooks/use-chat";
import type { FileEntry } from "../hooks/use-files";
import { t, getLang, setLang, useLang } from "../lib/i18n";
import { track } from "../lib/posthog";
import { toggleDark, cn } from "../lib/utils";
import { useToast } from "../lib/toast";
import { useSpeechRecognition } from "../hooks/use-speech";
import { useUrlParam } from "../hooks/use-url-param";
import { useMediaQuery } from "../hooks/use-media-query";
import { usePaneWidth } from "../hooks/use-pane-width";
import { SUGGESTIONS } from "./suggestions-data";

export interface PassAgent {
  slug: string;
  title: string;
  title_ar?: string;
  description: string;
  description_ar?: string;
  link: string;
  icon_svg?: string;
}

export interface AccountInfo {
  user: UserInfo;
  plan?: PlanInfo;
  org?: { id: string; name: string } | null;
  activeOrg?: { id: string; name: string; imageUrl?: string };
  orgs?: { id: string; name: string; imageUrl: string }[];
  onSignOut: () => void;
  onManageAccount: () => void;
  onCreateOrg: () => void;
  onManageOrg: () => void;
  onSwitchOrg: (orgId: string | null) => void;
  workspaces?: WorkspacesMenu;
}

export interface FilesPanelProps {
  entries: FileEntry[];
  path: string;
  loading: boolean;
  onNavigate: (dir: string) => void;
  onUpload: (dir: string, file: File) => Promise<void>;
  onUploadBatch?: (dir: string, files: { rel: string; file: File }[]) => Promise<void>;
  onMkdir: (dir: string, name: string) => Promise<void>;
  onRename: (from: string, to: string) => Promise<void>;
  onDelete: (path: string) => Promise<void>;
  onOpenFile: (path: string) => Promise<string>;
  readFile: (path: string) => Promise<string>;
  writeFile: (path: string, text: string) => Promise<void>;
  searchFiles: (query: string) => Promise<{ name: string; path: string }[]>;
  listFolders: () => Promise<{ name: string; path: string }[]>;
  onShareFile?: (path: string, audience: string) => Promise<string>;
  onOpenInCanvas?: (path: string, name: string) => void;
  maxUpload?: number;   // per-file cap (MB) for the client pre-check
  org?: { id: string; name: string } | null;
}

export function Chat({ chat, onShare, files, account, config }: {
  chat: ChatApi;
  onShare?: (audience: string) => Promise<string>;
  files?: FilesPanelProps;
  account?: AccountInfo | null;
  config?: AppConfig | null;
}) {
  const { messages, isStreaming, chatLoading, chatId, send: onSend, retry: onRetry, stop: onStop, clear: onClear, listShares: onListShares, deleteShare: onDeleteShare, listChats: onListChats, loadChat: onLoadChat, deleteChat: onDeleteChat, renameChat: onRenameChat, setFavorite: onSetFavorite, uploadFile, authHeaders, setUIHandler } = chat;
  const { user, plan, org, activeOrg, orgs, onSignOut, onManageAccount, onCreateOrg, onManageOrg, onSwitchOrg, workspaces } = account ?? ({} as Partial<AccountInfo>);
  const { name, pass_metadata: passMetadata, voice, suggestions } = config ?? {};

  const lang = useLang();
  const { error: toastError } = useToast();
  const isAr = lang === "ar";
  // logo and brand inherit from en; name/description stay per-locale.
  const _active = passMetadata?.[isAr ? "ar" : "en"];
  const _en = passMetadata?.en;
  const meta = _active
    ? { ..._active, logo: _active.logo || _en?.logo || "", brand: _active.brand || _en?.brand || "" }
    : _en;
  const inputPlaceholder = meta
    ? (isAr ? `اسأل ${meta.name} - اكتب @ لذكر ملف` : `Ask ${meta.name} - @ to mention a file`)
    : undefined;
  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [exploreOpen, setExploreOpen] = useState(false);
  const [exploreAgents, setExploreAgents] = useState<PassAgent[]>([]);
  const [exploreLoading, setExploreLoading] = useState(false);
  const [filesOpen, setFilesOpen] = useState(false);
  const [filesTab, setFilesTab] = useState<"files" | "shares" | "chats">(account ? "chats" : "files");
  const [canvasTabs, setCanvasTabs] = useState<CanvasFile[]>([]);
  const [canvasActive, setCanvasActive] = useState<string | null>(null);
  const [canvasHidden, setCanvasHidden] = useState(false);
  const [canvasExpanded, setCanvasExpanded] = useState(false);
  const isDesktop = useMediaQuery("(min-width: 1024px)");
  useEffect(() => {
    if (canvasHidden || canvasTabs.length === 0) setCanvasExpanded(false);
  }, [canvasHidden, canvasTabs.length]);
  const openFileInCanvas = useCallback((path: string, name?: string) => {
    setCanvasTabs((tabs) => (tabs.some((f) => f.path === path) ? tabs : [...tabs, { path, name: name || path.split("/").pop() || path }]));
    setCanvasActive(path);
    setCanvasHidden(false);
  }, []);
  const closeCanvasTab = useCallback((path: string) => {
    setCanvasTabs((tabs) => tabs.filter((f) => f.path !== path));
    setCanvasActive((a) => (a === path ? null : a));
  }, []);
  const [panelExpanded, setPanelExpanded] = useState(false);
  // Drag the panel's left edge to resize; width persists across sessions.
  const { width: panelWidth, startResize } = usePaneWidth("cycls_panel_width", 480, 360, 80);
  const [shareOpen, setShareOpen] = useState(false);
  const [shares, setShares] = useState<{ token: string; path: string; audience: string; title: string; shared_at: string; url: string }[]>([]);
  const [sharesLoading, setSharesLoading] = useState(false);
  const [chats, setChats] = useState<{ id: string; title: string; updatedAt: string; favoritedAt?: string }[]>([]);
  const [chatsLoading, setChatsLoading] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { scrollRef, contentRef, scrollToBottom } = useStickToBottom();

  const handleSubmitRef = useRef<(overrideText?: string, origin?: string) => void>(() => {});
  const [pricingFor, setPricingFor] = useState<"user" | "organization" | null>(null);
  const openPricing = useCallback((payer: "user" | "organization", source: string) => {
    setPricingFor(payer);
    track("plan_modal_opened", { payer_type: payer, source });
  }, []);
  const closePricing = useCallback((method: string) => {
    setPricingFor((cur) => {
      if (cur) track("plan_modal_closed", { payer_type: cur, method });
      return null;
    });
  }, []);

  useUrlParam("plans", (plans) => {
    if (plans === "b2c") openPricing("user", "url_param");
    else if (plans === "b2b") activeOrg ? openPricing("organization", "url_param") : onCreateOrg?.();
  });

  useEffect(() => {
    if (!setUIHandler) return;
    setUIHandler((ev) => {
      if (ev.action === "open_plan_modal") {
        openPricing(activeOrg ? "organization" : "user", "agent_event");
      } else if (ev.action === "open_canvas" && typeof ev.path === "string") {
        openFileInCanvas(ev.path, typeof ev.name === "string" ? ev.name : undefined);
      }
    });
    return () => setUIHandler(null);
  }, [setUIHandler, activeOrg, openPricing, openFileInCanvas]);

  const onSpeechEnd = useCallback((text: string) => {
    if (text.trim()) {
      handleSubmitRef.current(text, "voice");
      textareaRef.current?.blur();
    }
  }, []);
  const { listening, transcribing, start: startMic, stop: stopMic, cancel: cancelMic } = useSpeechRecognition({ onEnd: onSpeechEnd, authHeaders });

  // Reset sidebar data when org changes
  useEffect(() => {
    setChats([]);
    setShares([]);
    setFilesOpen(false);
  }, [activeOrg?.id]);

  const handleFilesAdded = useCallback(async (incoming: File[]) => {
    // Reject oversized files up front (server enforces the same cap).
    const maxMb = config?.max_upload ?? 512;
    const newFiles = incoming.filter((f) => f.size <= maxMb * 1024 * 1024);
    const skipped = incoming.length - newFiles.length;
    if (skipped) toastError(`${skipped === 1 ? "File" : `${skipped} files`} over the ${maxMb} MB limit ${skipped === 1 ? "was" : "were"} skipped.`);
    if (!newFiles.length) return;
    if (uploadFile) {
      // Add placeholders immediately — blob URL is a stable key per file
      const placeholders: Attachment[] = newFiles.map((f) => ({
        name: f.name,
        size: f.size,
        type: f.type,
        url: URL.createObjectURL(f),
        status: "uploading" as const,
      }));
      setAttachments((prev) => [...prev, ...placeholders]);

      // Upload each file and update in place by matching blob URL
      placeholders.forEach((placeholder, i) => {
        uploadFile(newFiles[i]).then((result) => {
          setAttachments((prev) => prev.map((att) =>
            att.url === placeholder.url ? { ...att, path: result.path, status: undefined } : att
          ));
        }).catch(() => {
          setAttachments((prev) => prev.map((att) =>
            att.url === placeholder.url ? { ...att, status: "error" as const } : att
          ));
        });
      });
    } else {
      const newAttachments = newFiles.map((f) => ({
        name: f.name,
        size: f.size,
        type: f.type,
        url: URL.createObjectURL(f),
      }));
      setAttachments((prev) => [...prev, ...newAttachments]);
    }
  }, [uploadFile, config?.max_upload, toastError]);

  const removeFile = useCallback((index: number) => {
    setAttachments((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const openFilePicker = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

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

  const handleSubmit = useCallback((overrideText?: string, origin: string = "keyboard") => {
    const text = (overrideText ?? input).trim();
    if (!text || isStreaming || attachments.some((a) => a.status === "uploading")) return;
    const sendAttachments = attachments.length > 0 ? [...attachments] : undefined;
    setInput("");
    setAttachments([]);
    onSend(text, sendAttachments, origin);
    setTimeout(() => scrollToBottom(), 0);
  }, [input, isStreaming, onSend, attachments, scrollToBottom]);

  handleSubmitRef.current = handleSubmit;

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    const isMobile = window.matchMedia("(pointer: coarse)").matches;
    if (e.key === "Enter" && !e.shiftKey && !isMobile) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const isEmpty = messages.length === 0;

  // Static config, then the 1h localStorage cache, then the network.
  const loadExplore = useCallback(async (): Promise<PassAgent[]> => {
    if (config?.explore?.length) return config.explore;  // static: no network
    const CACHE_KEY = "cycls_explore";
    try {
      const cached = JSON.parse(localStorage.getItem(CACHE_KEY) || "null");
      if (cached && Date.now() - cached.at < 3_600_000 && cached.agents?.length) return cached.agents;
    } catch { /* ignore */ }
    const res = await fetch("/explore");
    const data = await res.json();
    localStorage.setItem(CACHE_KEY, JSON.stringify({ at: Date.now(), agents: data.agents || [] }));
    return data.agents || [];
  }, [config]);

  const openExplore = async () => {
    setExploreOpen(true);
    track("explore_opened", { cached: exploreAgents.length > 0 });
    if (exploreAgents.length > 0) return;
    setExploreLoading(true);
    try { setExploreAgents(await loadExplore()); } catch { /* silent */ }
    setExploreLoading(false);
  };

  // Switch the side panel's active tab and (re)load its data.
  const selectTab = (tab: "files" | "shares" | "chats") => {
    setFilesTab(tab);
    if (tab === "chats" && onListChats) {
      setChatsLoading(true);
      onListChats().then((items) => { setChats(items); setChatsLoading(false); }).catch(() => setChatsLoading(false));
    } else if (tab === "shares" && onListShares) {
      setSharesLoading(true);
      onListShares().then((items) => { setShares(items); setSharesLoading(false); }).catch(() => setSharesLoading(false));
    } else if (tab === "files" && files) {
      files.onNavigate(files.path);
    }
  };

  // Open the panel, keeping the last-active tab unless one is given.
  const openPanel = (tab?: "files" | "shares" | "chats") => {
    selectTab(tab ?? filesTab);
    setFilesOpen(true);
  };

  const inputProps = {
    textareaRef, input, setInput, handleKeyDown, handleSubmit, isStreaming, onStop,
    onOpenFilePicker: openFilePicker,
    onOpenFiles: files ? () => openPanel("files") : undefined,
    attachments,
    onRemoveFile: removeFile,
    listening, transcribing, startMic, stopMic, cancelMic, voice,
    onFilesAdded: handleFilesAdded,
    onMentionSearch: files?.searchFiles,
    placeholder: inputPlaceholder,
  };

  return (
    <div className="h-dvh flex">
      <div className="flex h-full min-w-0 flex-1 flex-col">
      <header className="relative z-30 h-12 shrink-0" dir="ltr">
        <div className="mx-auto flex h-full max-w-full items-center justify-between px-4 sm:px-6">
          <div className="flex items-center gap-2">
          {meta?.brand ? (
            <span className="flex h-6 items-center">
              {meta.brand.startsWith("<") ? (
                <span className="flex h-6 items-center [&>svg]:h-6 [&>svg]:w-auto" dangerouslySetInnerHTML={{ __html: meta.brand }} />
              ) : (
                <img src={meta.brand} alt="" className="h-6 w-auto object-contain" />
              )}
            </span>
          ) : (
            <a href="https://cycls.ai" className="flex items-center gap-2 text-foreground hover:opacity-80 transition-opacity">
              <CyclsLogo className="h-5 fill-muted-foreground" />
            </a>
          )}
          {name && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span className="text-muted-foreground/40">|</span>
              {config?.explore_enabled ? (
                <button
                  onClick={openExplore}
                  className="flex items-center gap-1 text-foreground font-medium capitalize hover:opacity-70 transition-opacity cursor-pointer"
                >
                  {meta?.name || name}
                  <Icon name="chevron-down" className="w-3 h-3 text-muted-foreground" />
                </button>
              ) : (
                <span className="text-foreground font-medium capitalize">{meta?.name || name}</span>
              )}
            </div>
          )}
          </div>
          <div className="flex items-center gap-1">
            {messages.length > 0 && (
              <>
                <button
                  onClick={() => { onClear(); setTimeout(() => textareaRef.current?.focus(), 0); }}
                  className="text-muted-foreground hover:text-foreground hover:bg-secondary/80 rounded-lg p-2 transition-colors cursor-pointer"
                  aria-label="New chat"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                  </svg>
                </button>
                {onShare && !isStreaming && (
                  <>
                    <button
                      onClick={() => setShareOpen((o) => !o)}
                      className="text-muted-foreground hover:text-foreground hover:bg-secondary/80 rounded-lg p-2 transition-colors cursor-pointer"
                      aria-label="Share"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                      </svg>
                    </button>
                    {shareOpen && (
                      <ShareDialog
                        onClose={() => setShareOpen(false)}
                        org={org}
                        onShare={onShare}
                        onManageShares={account ? () => { setShareOpen(false); openPanel("shares"); } : undefined}
                      />
                    )}
                  </>
                )}
              </>
            )}
            {!user && (
              <>
                <IconButton name="moon" onClick={() => toggleDark("header")} label="Toggle theme" />
                <button
                  onClick={() => {
                    const next = isAr ? "en" : "ar";
                    setLang(next);
                    track("language_changed", { to: next, source: "header" });
                  }}
                  className="text-muted-foreground hover:text-foreground hover:bg-secondary/80 rounded-lg p-2 transition-colors cursor-pointer"
                  aria-label="Toggle language"
                >
                  <span className="text-xs font-medium w-4 h-4 flex items-center justify-center">{isAr ? "En" : "ع"}</span>
                </button>
              </>
            )}
            {workspaces && <WorkspaceSwitcher workspaces={workspaces} />}
            {files && canvasTabs.length > 0 && (
              <button
                onClick={() => setCanvasHidden((h) => !h)}
                className={`${canvasHidden ? "text-muted-foreground" : "text-foreground"} hover:text-foreground hover:bg-secondary/80 rounded-lg p-2 transition-colors cursor-pointer`}
                aria-label={canvasHidden ? "Show canvas" : "Hide canvas"}
                title={canvasHidden ? "Show canvas" : "Hide canvas"}
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <rect x="3.75" y="3.75" width="16.5" height="16.5" rx="2" />
                  <path d="M14.25 4.75h3.5a1.5 1.5 0 011.5 1.5v11.5a1.5 1.5 0 01-1.5 1.5h-3.5z" fill={canvasHidden ? "none" : "currentColor"} stroke="none" />
                </svg>
              </button>
            )}
            {(files || account) && (
              <button
                onClick={() => filesOpen ? setFilesOpen(false) : openPanel()}
                className="text-muted-foreground hover:text-foreground hover:bg-secondary/80 rounded-lg p-2 transition-colors cursor-pointer"
                aria-label="Menu"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 3.75v16.5M3.75 3.75h16.5v16.5H3.75M9.75 3.75v16.5" />
                </svg>
              </button>
            )}
            {user && <div className="ml-1"><UserMenu user={user} onSignOut={onSignOut} onManageAccount={onManageAccount} onCreateOrg={onCreateOrg} onManageOrg={onManageOrg} onSwitchOrg={onSwitchOrg} activeOrg={activeOrg} orgs={orgs} plan={plan} onOpenPlans={() => openPricing(activeOrg ? "organization" : "user", "user_menu")} /></div>}
          </div>
        </div>
      </header>

      {/* Explore agents dropdown */}
      <Popover open={exploreOpen} onClose={() => setExploreOpen(false)} className="left-4 sm:left-6 top-12 mt-1 w-72 rounded-lg border border-border bg-background shadow-lg overflow-hidden">
        <div dir={isAr ? "rtl" : "ltr"}>
          <div className="px-3 py-2 border-b border-border">
            <p className="text-xs font-medium text-muted-foreground">{t("explore")}</p>
          </div>
          {exploreLoading ? (
            <div className="flex items-center justify-center py-6">
              <div className="size-4 border-2 border-muted-foreground/30 border-t-foreground rounded-full animate-spin" />
            </div>
          ) : (
            <div className="max-h-80 overflow-y-auto py-1">
              {exploreAgents.map((agent) => {
                const agentTitle = (isAr && agent.title_ar) || agent.title;
                const agentDesc = (isAr && agent.description_ar) || agent.description;
                const href = agent.link.startsWith("http") ? agent.link : `https://${agent.link}`;
                return (
                  <a
                    key={agent.slug}
                    href={href}
                    onClick={() => track("explore_agent_clicked", {
                      agent_slug: agent.slug,
                      agent_title: agent.title,
                      agent_link: href,
                    })}
                    className="flex items-start gap-3 px-3 py-2.5 text-sm hover:bg-secondary/80 transition-colors cursor-pointer"
                  >
                    {agent.icon_svg ? (
                      agent.icon_svg.startsWith("<") ? (
                        <div className="size-8 shrink-0 rounded-md overflow-hidden" dangerouslySetInnerHTML={{ __html: agent.icon_svg }} />
                      ) : (
                        <img src={agent.icon_svg} alt="" className="size-8 shrink-0 rounded-md object-cover" />
                      )
                    ) : (
                      <div className="size-8 shrink-0 rounded-md bg-secondary flex items-center justify-center text-xs font-medium uppercase text-muted-foreground">
                        {agentTitle?.[0]}
                      </div>
                    )}
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-foreground truncate">{agentTitle}</p>
                      <p className="text-xs text-muted-foreground line-clamp-2 mt-0.5">{agentDesc}</p>
                    </div>
                  </a>
                );
              })}
            </div>
          )}
        </div>
      </Popover>

      {/* Stable file input — lives outside LayoutGroup so it survives remounts */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        className="hidden"
        onChange={(e) => {
          if (e.target.files?.length) {
            handleFilesAdded(Array.from(e.target.files));
            e.target.value = "";
          }
        }}
      />

      {/* rtl:flex-row-reverse keeps the canvas on the right in Arabic */}
      <div className="flex min-h-0 flex-1 rtl:flex-row-reverse">
      <div className={cn("relative flex h-full min-w-0 flex-1 flex-col", isDesktop && canvasExpanded && !canvasHidden && canvasTabs.length > 0 && "hidden")}>
      <LayoutGroup>
        <LoadingBar active={chatLoading} />
        {!chatLoading && (isEmpty ? (
          <div className="flex-1 flex flex-col items-center justify-center px-6 pb-16 pt-40 sm:pt-0">
            <div className="relative max-w-3xl w-full">
              {meta && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: 0.4 }}
                  className="absolute bottom-full left-0 right-0 flex flex-col items-center gap-4 mb-10 text-center"
                >
                  {meta.logo && (meta.logo.startsWith("<") ? (
                    <div className="size-16 rounded-xl overflow-hidden border border-border" dangerouslySetInnerHTML={{ __html: meta.logo }} />
                  ) : (
                    <img src={meta.logo} alt="" className="size-16 rounded-xl object-cover border border-border" />
                  ))}
                  <h2 className="text-2xl font-semibold text-foreground">{meta.name}</h2>
                  {meta.description && <p className="text-base text-muted-foreground max-w-lg">{meta.description}</p>}
                </motion.div>
              )}
              <InputBox {...inputProps} />
              {suggestions && (
                <div className="relative">
                  <div className="absolute inset-x-0 top-0">
                    <Suggestions
                      onSelect={(text) => handleSubmit(text, "suggestion")}
                      onPreview={(text) => setInput(text)}
                      input={input}
                    />
                  </div>
                </div>
              )}
            </div>
          </div>
        ) : (
          <>
            <div ref={scrollRef} className="isolate relative flex-1 overflow-y-auto" dir="ltr">
              <div className="pointer-events-none sticky top-0 z-10 h-6 -mb-6 bg-[linear-gradient(to_bottom,var(--color-background)_0%,var(--color-background)_20%,transparent_100%)]" />
              <div ref={contentRef} className="flex w-full flex-col items-center py-4">
                {messages.map((msg, i) => {
                  const isLast = i === messages.length - 1;
                  const hasError = msg.role === "assistant" && msg.parts?.some((p) => p.type === "callout" && p.style === "error");
                  return (
                    <MessageBubble
                      key={i}
                      message={msg}
                      isStreaming={
                        isStreaming &&
                        isLast &&
                        msg.role === "assistant"
                      }
                      onRetry={isLast && hasError && !isStreaming ? onRetry : undefined}
                      onOpenFile={openFileInCanvas}
                    />
                  );
                })}
              </div>
              <div className="pointer-events-none sticky bottom-0 z-10 h-6 -mt-6 bg-[linear-gradient(to_top,var(--color-background)_0%,var(--color-background)_20%,transparent_100%)]" />
            </div>
            <div className="shrink-0 px-6 pb-2 pt-1">
              <div className="max-w-3xl mx-auto">
                <InputBox {...inputProps} />
              </div>
            </div>
          </>
        ))}
      </LayoutGroup>

      {/* Files / Shares / Sessions panel */}
      <AnimatePresence>
        {filesOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
              className="fixed inset-0 z-50 bg-black/30 backdrop-blur-[2px]"
              onClick={() => setFilesOpen(false)}
            />
            <motion.div
              initial={{ x: "100%" }}
              animate={{ x: 0 }}
              exit={{ x: "100%" }}
              transition={{ type: "spring", damping: 25, stiffness: 200 }}
              className={cn(
                "fixed z-50 rounded-xl border border-border bg-background flex flex-col overflow-hidden",
                panelExpanded ? "inset-2" : "top-1 right-1 bottom-1 w-[calc(100%-0.5rem)] max-w-[calc(100%-0.5rem)]",
              )}
              style={panelExpanded ? undefined : { width: panelWidth }}
            >
              {/* Resize handle (left edge) — desktop only */}
              {!panelExpanded && (
                <div
                  onMouseDown={startResize}
                  className="absolute left-0 top-0 bottom-0 z-20 hidden sm:block w-1.5 -ml-0.5 cursor-ew-resize hover:bg-accent/30"
                  aria-label="Resize panel"
                />
              )}
              {/* Tab bar */}
              {(files || account) && (
                <div className="flex items-center border-b border-border px-4 sm:px-6">
                  {account && (
                    <button
                      onClick={() => selectTab("chats")}
                      className={`px-3 py-3 text-sm font-medium border-b-2 transition-colors cursor-pointer ${filesTab === "chats" ? "border-foreground text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`}
                    >
                      {t("chats")}
                    </button>
                  )}
                  {files && (
                    <button
                      onClick={() => selectTab("files")}
                      className={`px-3 py-3 text-sm font-medium border-b-2 transition-colors cursor-pointer ${filesTab === "files" ? "border-foreground text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`}
                    >
                      {t("files")}
                    </button>
                  )}
                  {account && (
                    <button
                      onClick={() => selectTab("shares")}
                      className={`px-3 py-3 text-sm font-medium border-b-2 transition-colors cursor-pointer ${filesTab === "shares" ? "border-foreground text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`}
                    >
                      {t("shares")}
                    </button>
                  )}
                  <div className="flex-1" />
                  <button
                    onClick={() => setPanelExpanded((e) => !e)}
                    className="hidden sm:flex size-8 items-center justify-center rounded-lg text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
                    aria-label={panelExpanded ? t("collapse") : t("expand")}
                    title={panelExpanded ? t("collapse") : t("expand")}
                  >
                    <Icon name={panelExpanded ? "collapse" : "expand"} className="size-4" />
                  </button>
                  <button
                    onClick={() => setFilesOpen(false)}
                    className="flex size-8 items-center justify-center rounded-lg text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
                    aria-label="Close"
                  >
                    <Icon name="x" className="size-4" />
                  </button>
                </div>
              )}
              {filesTab === "files" && files ? (
                <Files {...files} onOpenInCanvas={(path, name) => { openFileInCanvas(path, name); if (isDesktop) setFilesOpen(false); }} maxUpload={config?.max_upload} />
              ) : filesTab === "shares" ? (
                <div className="flex flex-1 min-h-0 flex-col">
                  <div className="flex-1 overflow-y-auto">
                    {sharesLoading ? (
                      <LoadingBar />
                    ) : shares.length === 0 ? (
                      <EmptyState
                        icon={<Icon name="link" className="size-full" strokeWidth={1.5} />}
                        title={t("noShares")}
                        subtitle={t("noSharesSub")}
                      />
                    ) : (
                      <div className="divide-y divide-border">
                        {shares.map((s) => {
                          const isChat = s.path.startsWith("chat/");
                          const audienceLabel = s.audience === "public"
                            ? t("anyoneWithLink")
                            : (org && s.audience === `org:${org.id}`) ? org.name : "Org";
                          return (
                          <div key={s.token} className="group relative flex items-center gap-3 px-4 py-2.5 sm:px-6 hover:bg-secondary/50 transition-colors cursor-pointer"
                            onClick={() => window.open(s.url, "_blank")}
                          >
                            <div className="bg-secondary flex size-8 shrink-0 items-center justify-center rounded-lg">
                              <svg className="size-4 text-muted-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                {isChat ? (
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                                ) : (
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                                )}
                              </svg>
                            </div>
                            <div className="flex-1 min-w-0">
                              <span className="text-sm text-foreground truncate block">{s.title || t("untitled")}</span>
                              <span className="text-[10px] text-muted-foreground/70 truncate block">{audienceLabel}</span>
                            </div>
                            <span className="hidden sm:block text-xs text-muted-foreground shrink-0 w-16 text-right">
                              {formatShortDate(s.shared_at)}
                            </span>
                            {onDeleteShare && (
                              <div className="relative shrink-0">
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setSharesLoading(true);
                                    onDeleteShare(s.token).then(() => {
                                      setShares((prev) => prev.filter((x) => x.token !== s.token));
                                    }).finally(() => setSharesLoading(false));
                                  }}
                                  className="flex size-7 items-center justify-center rounded-md text-muted-foreground sm:opacity-0 sm:group-hover:opacity-100 hover:text-red-500 hover:bg-red-500/10 transition-all cursor-pointer"
                                  aria-label="Delete share"
                                >
                                  <svg className="size-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" d="M13.181 8.68a4 4 0 00-5.34.638l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.34-.638l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                                    <path strokeLinecap="round" strokeLinejoin="round" d="M4 4l16 16" />
                                  </svg>
                                </button>
                              </div>
                            )}
                          </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                </div>
              ) : filesTab === "chats" ? (
                <ChatsPanel
                  chats={chats}
                  loading={chatsLoading}
                  activeId={chatId}
                  onLoad={(id) => { onLoadChat?.(id); if (window.innerWidth < 640) setFilesOpen(false); }}
                  onDelete={(id) => { setChatsLoading(true); onDeleteChat?.(id).then(() => setChats((prev) => prev.filter((x) => x.id !== id))).finally(() => setChatsLoading(false)); }}
                  onRename={async (id, title) => {
                    await onRenameChat?.(id, title);
                    setChats((prev) => prev.map((x) => x.id === id ? { ...x, title } : x));
                  }}
                  onToggleFavorite={async (id, on) => {
                    await onSetFavorite?.(id, on);
                    setChats((prev) => prev.map((x) => x.id === id ? { ...x, favoritedAt: on ? new Date().toISOString() : "" } : x));
                  }}
                />
              ) : null}
            </motion.div>
          </>
        )}
      </AnimatePresence>
      {pricingFor && (
        <Popover open onClose={() => closePricing("backdrop")} dim className="inset-0 flex items-center justify-center pointer-events-none">
          <div dir="ltr" className="pointer-events-auto fixed top-1 right-1 bottom-1 w-[calc(100%-0.5rem)] flex flex-col rounded-xl border border-border bg-background shadow-xl sm:relative sm:inset-auto sm:w-auto sm:max-h-[90vh] sm:rounded-2xl">
            <div className="flex items-center justify-between px-6 pt-5 pb-3">
              <h2 className="text-base font-semibold text-foreground flex items-center gap-2">
                {pricingFor === "organization" ? (
                  activeOrg ? (
                    <>
                      <span>{t("orgPlansFor")}</span>
                      <span className="inline-flex items-center gap-1.5 text-sm font-medium bg-secondary text-foreground rounded-lg px-2.5 py-1">
                        {activeOrg.imageUrl && (
                          <div
                            className="size-4 rounded-full bg-secondary shrink-0"
                            style={{ backgroundImage: `url(${activeOrg.imageUrl})`, backgroundSize: "cover" }}
                          />
                        )}
                        {activeOrg.name}
                      </span>
                    </>
                  ) : t("orgPlans")
                ) : t("personalPlans")}
              </h2>
              <button
                onClick={() => closePricing("dismiss")}
                className="text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
              >
                <Icon name="x" className="w-4 h-4" />
              </button>
            </div>
            <div className="px-6 pb-5 overflow-y-auto">
              <PricingCards payerType={pricingFor} onSelect={() => closePricing("select")} />
            </div>
          </div>
        </Popover>
      )}
      </div>
      {files && (
        <Canvas
          tabs={canvasTabs}
          active={canvasActive}
          docked={isDesktop}
          hidden={canvasHidden}
          expanded={canvasExpanded}
          onToggleExpand={() => setCanvasExpanded((e) => !e)}
          onSelectTab={setCanvasActive}
          onCloseTab={closeCanvasTab}
          onHide={() => setCanvasHidden(true)}
          onAddFile={openFileInCanvas}
          searchFiles={files.searchFiles}
          readFile={files.readFile}
          openFile={files.onOpenFile}
          writeFile={files.writeFile}
          onShareFile={files.onShareFile}
        />
      )}
      </div>
      </div>
    </div>
  );
}


function EmptyState({ icon, title, subtitle }: { icon: React.ReactNode; title: string; subtitle: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-muted-foreground">
      <div className="size-10 mb-3 opacity-30">{icon}</div>
      <p className="text-sm">{title}</p>
      <p className="text-xs mt-1">{subtitle}</p>
    </div>
  );
}

function formatShortDate(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function ChatsPanel({ chats, loading, activeId, onLoad, onDelete, onRename, onToggleFavorite }: {
  chats: { id: string; title: string; updatedAt: string; favoritedAt?: string }[];
  loading: boolean;
  activeId?: string | null;
  onLoad: (id: string) => void;
  onDelete: (id: string) => void;
  onRename: (id: string, title: string) => Promise<void>;
  onToggleFavorite: (id: string, on: boolean) => Promise<void>;
}) {
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState<string | null>(null);

  if (loading) return <LoadingBar />;

  if (chats.length === 0) {
    return (
      <EmptyState
        icon={<Icon name="list" className="size-full" strokeWidth={1.5} />}
        title={t("noChats")}
        subtitle={t("noChatsSub")}
      />
    );
  }

  const visible = favoritesOnly ? chats.filter((c) => c.favoritedAt) : chats;

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="flex items-center gap-2 px-4 sm:px-6 py-2 border-b border-border">
        <button
          onClick={() => setFavoritesOnly((v) => !v)}
          className={`flex items-center gap-1.5 px-2 py-1 rounded-md text-xs transition-colors cursor-pointer ${favoritesOnly ? "bg-secondary text-foreground" : "text-muted-foreground hover:bg-secondary/50"}`}
          aria-label="Favorites only"
        >
          <Star filled={favoritesOnly} className="size-3.5" />
          {t("favorites")}
        </button>
      </div>
      <div className="flex-1 overflow-y-auto divide-y divide-border">
        {visible.map((s) => {
          const isFav = !!s.favoritedAt;
          return (
            <div
              key={s.id}
              className={`group relative flex items-center gap-3 px-4 py-2.5 sm:px-6 hover:bg-secondary/50 transition-colors cursor-pointer ${activeId === s.id ? "bg-secondary/30" : ""}`}
              onClick={() => onLoad(s.id)}
            >
              <button
                onClick={(e) => { e.stopPropagation(); onToggleFavorite(s.id, !isFav); }}
                className={`flex size-7 shrink-0 items-center justify-center rounded-md transition-colors cursor-pointer ${isFav ? "text-yellow-500" : "text-muted-foreground/40 hover:text-yellow-500"}`}
                aria-label={isFav ? "Unfavorite" : "Favorite"}
              >
                <Star filled={isFav} className="size-4" />
              </button>
              <div className="flex-1 min-w-0">
                {renaming === s.id ? (
                  <InlineInput
                    initial={s.title || ""}
                    onSubmit={async (newTitle) => {
                      setRenaming(null);
                      if (newTitle !== s.title) await onRename(s.id, newTitle);
                    }}
                    onCancel={() => setRenaming(null)}
                  />
                ) : (
                  <span className="text-sm text-foreground truncate block">{s.title || t("untitled")}</span>
                )}
              </div>
              <span className="hidden sm:block text-xs text-muted-foreground shrink-0 w-16 text-right">
                {s.updatedAt ? formatShortDate(s.updatedAt) : ""}
              </span>
              <div className="relative shrink-0">
                <button
                  onClick={(e) => { e.stopPropagation(); setMenuOpen(menuOpen === s.id ? null : s.id); }}
                  className="flex size-7 items-center justify-center rounded-md text-muted-foreground sm:opacity-0 sm:group-hover:opacity-100 hover:text-foreground hover:bg-secondary transition-all cursor-pointer"
                  aria-label="Actions"
                >
                  <svg className="size-4" fill="currentColor" viewBox="0 0 24 24">
                    <circle cx="12" cy="5" r="1.5" />
                    <circle cx="12" cy="12" r="1.5" />
                    <circle cx="12" cy="19" r="1.5" />
                  </svg>
                </button>
                {menuOpen === s.id && (
                  <DropdownMenu
                    onClose={() => setMenuOpen(null)}
                    items={[
                      { label: t("rename"), onClick: () => setRenaming(s.id) },
                      { label: t("delete"), danger: true, onClick: () => onDelete(s.id) },
                    ]}
                  />
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Star({ filled, className }: { filled: boolean; className?: string }) {
  return (
    <svg className={className} fill={filled ? "currentColor" : "none"} stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
    </svg>
  );
}

function Suggestions({
  onSelect,
  onPreview,
  input,
}: {
  onSelect: (text: string) => void;
  onPreview: (text: string) => void;
  input: string;
}) {
  const [activeCategory, setActiveCategory] = useState<string | null>(null);
  const lang = getLang();
  const suggestions = SUGGESTIONS[lang] || SUGGESTIONS.en;

  // Reset active category when input is cleared
  useEffect(() => {
    if (!input && activeCategory) {
      setActiveCategory(null);
    }
  }, [input, activeCategory]);

  const activeSuggestion = suggestions.find((s) => s.label === activeCategory);

  return (
    <div className="mt-3 px-1">
      <AnimatePresence mode="wait">
        {!activeCategory ? (
          <motion.div
            key="categories"
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.15 }}
            className="flex flex-wrap gap-2 justify-center max-h-10 overflow-hidden"
          >
            {suggestions.map((s, i) => (
              <motion.button
                key={s.label}
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ duration: 0.15, delay: i * 0.02 }}
                onClick={() => {
                  setActiveCategory(s.label);
                  onPreview(s.highlight);
                  track("suggestion_category_selected", { category: s.label });
                }}
                className="flex items-center gap-2 rounded-full border border-border px-3.5 py-2 text-sm text-muted-foreground hover:text-foreground hover:border-foreground/30 hover:bg-secondary/50 transition-colors cursor-pointer"
              >
                {s.icon}
                {s.label}
              </motion.button>
            ))}
          </motion.div>
        ) : (
          <motion.div
            key="items"
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.15 }}
            className="flex flex-col gap-1"
          >
            {activeSuggestion?.items.map((item, i) => {
              const highlight = activeSuggestion.highlight;
              const idx = item.indexOf(highlight);
              return (
                <motion.button
                  key={item}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.15, delay: i * 0.05 }}
                  onClick={() => {
                    track("suggestion_prompt_clicked", {
                      category: activeSuggestion.label,
                      prompt: item,
                    });
                    onSelect(item);
                    setActiveCategory(null);
                  }}
                  className="w-full text-start px-3 py-2 rounded-xl text-sm text-muted-foreground hover:bg-secondary/50 transition-colors cursor-pointer"
                >
                  {idx >= 0 ? (
                    <>
                      {item.slice(0, idx)}
                      <span className="text-foreground font-medium">{highlight}</span>
                      {item.slice(idx + highlight.length)}
                    </>
                  ) : (
                    item
                  )}
                </motion.button>
              );
            })}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
