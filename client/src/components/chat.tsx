import { useState, useRef, useEffect, useCallback } from "react";
import { motion, LayoutGroup, AnimatePresence } from "framer-motion";
import { useStickToBottom } from "use-stick-to-bottom";
import { MessageBubble } from "./message";
import { Files } from "./files";
import { Popover } from "./popover";
import { CyclsLogo } from "./cycls-logo";
import { LoadingBar } from "./loading-bar";
import { PricingCards } from "./pricing-cards";
import { UserMenu, type UserInfo, type PlanInfo } from "./user-menu";
import type { Message, Attachment, PassMetadata, UIHandler } from "../hooks/use-chat";
import type { FileEntry } from "../hooks/use-files";
import { t, getLang, setLang, useLang } from "../lib/i18n";
import { track } from "../lib/posthog";
import { toggleDark } from "../lib/utils";
import { useSpeechRecognition } from "../hooks/use-speech";
import { useUrlParam } from "../hooks/use-url-param";
import { SUGGESTIONS } from "./suggestions-data";

interface PassAgent {
  slug: string;
  title: string;
  title_ar?: string;
  description: string;
  description_ar?: string;
  link: string;
  icon_svg?: string;
}

export function Chat({
  messages,
  isStreaming,
  onSend,
  onStop,
  onClear,
  onRetry,
  onShare,
  org,
  onListShares,
  onDeleteShare,
  onListChats,
  onLoadChat,
  onDeleteChat,
  chatId,
  chatLoading,
  onSignOut,
  onManageAccount,
  onCreateOrg,
  onManageOrg,
  onSwitchOrg,
  activeOrg,
  orgs,
  plan,
  name,
  passMetadata,
  user,
  uploadFile,
  authHeaders,
  voice,
  files,
  setUIHandler,
}: {
  messages: Message[];
  isStreaming: boolean;
  onSend: (text: string, attachments?: Attachment[], origin?: string) => void;
  onStop: () => void;
  onClear: () => void;
  onRetry?: () => void;
  onShare?: (title: string, audience: string) => Promise<string>;
  org?: { id: string; name: string } | null;
  onListShares?: () => Promise<{ token: string; path: string; audience: string; title: string; shared_at: string; url: string }[]>;
  onDeleteShare?: (token: string) => Promise<void>;
  onListChats?: () => Promise<{ id: string; title: string; updatedAt: string }[]>;
  onLoadChat?: (id: string) => Promise<void>;
  onDeleteChat?: (id: string) => Promise<void>;
  chatId?: string | null;
  chatLoading?: boolean;
  onSignOut?: () => void;
  onManageAccount?: () => void;
  onCreateOrg?: () => void;
  onManageOrg?: () => void;
  onSwitchOrg?: (orgId: string | null) => void;
  activeOrg?: { id: string; name: string; imageUrl?: string };
  orgs?: { id: string; name: string; imageUrl: string }[];
  plan?: PlanInfo;
  name?: string;
  passMetadata?: { en: PassMetadata; ar: PassMetadata };
  user?: UserInfo;
  uploadFile?: (file: File) => Promise<Attachment>;
  authHeaders?: () => Promise<Record<string, string>>;
  voice?: boolean;
  setUIHandler?: (h: UIHandler | null) => void;
  files?: {
    entries: FileEntry[];
    path: string;
    loading: boolean;
    onNavigate: (dir: string) => void;
    onUpload: (dir: string, file: File) => Promise<void>;
    onMkdir: (dir: string, name: string) => Promise<void>;
    onRename: (from: string, to: string) => Promise<void>;
    onDelete: (path: string) => Promise<void>;
    onOpenFile: (path: string) => Promise<string>;
    onShareFile?: (path: string) => Promise<string>;
  };
}) {
  const lang = useLang();
  const isAr = lang === "ar";
  const meta = passMetadata?.[isAr ? "ar" : "en"];
  const inputPlaceholder = meta ? (isAr ? `اسأل ${meta.name}` : `Ask ${meta.name}`) : undefined;
  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [exploreOpen, setExploreOpen] = useState(false);
  const [exploreAgents, setExploreAgents] = useState<PassAgent[]>([]);
  const [exploreLoading, setExploreLoading] = useState(false);
  const [filesOpen, setFilesOpen] = useState(false);
  const [filesTab, setFilesTab] = useState<"files" | "shares" | "chats">("files");
  const [shareOpen, setShareOpen] = useState(false);
  const [shareTitle, setShareTitle] = useState("");
  const [shareAudience, setShareAudience] = useState<string>("public");
  const [shareUrl, setShareUrl] = useState<string | null>(null);
  const [shareLoading, setShareLoading] = useState(false);
  const [shareCopied, setShareCopied] = useState(false);
  const [shares, setShares] = useState<{ token: string; path: string; audience: string; title: string; shared_at: string; url: string }[]>([]);
  const [sharesLoading, setSharesLoading] = useState(false);
  const [chats, setChats] = useState<{ id: string; title: string; updatedAt: string }[]>([]);
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
      }
    });
    return () => setUIHandler(null);
  }, [setUIHandler, activeOrg, openPricing]);

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

  const handleFilesAdded = useCallback(async (newFiles: File[]) => {
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
  }, [uploadFile]);

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

  const openExplore = async () => {
    setExploreOpen(true);
    track("explore_opened", { cached: exploreAgents.length > 0 });
    if (exploreAgents.length > 0) return;
    setExploreLoading(true);
    try {
      const res = await fetch("https://cms.cycls.ai/agents");
      const data = await res.json();
      setExploreAgents(data.agents || []);
    } catch { /* silent */ }
    setExploreLoading(false);
  };

  const inputProps = {
    textareaRef, input, setInput, handleKeyDown, handleSubmit, isStreaming, onStop,
    onOpenFilePicker: uploadFile ? openFilePicker : undefined,
    onOpenFiles: files ? () => { setFilesOpen(true); setFilesTab("files"); files.onNavigate(files.path); } : undefined,
    attachments,
    onRemoveFile: removeFile,
    listening, transcribing, startMic, stopMic, cancelMic, voice,
    onFilesAdded: uploadFile ? handleFilesAdded : undefined,
    placeholder: inputPlaceholder,
  };

  return (
    <div className="h-dvh flex flex-col">
      {/* Header */}
      <header className="pointer-events-none fixed top-0 right-0 left-0 h-12" dir="ltr">
        <div className="pointer-events-auto mx-auto flex h-full max-w-full items-center justify-between px-4 sm:px-6">
          <div className="flex items-center gap-2">
          <a href="https://cycls.ai" className="flex items-center gap-2 text-foreground hover:opacity-80 transition-opacity">
            <CyclsLogo className="h-5 fill-muted-foreground" />
          </a>
          {name && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span className="text-muted-foreground/40">|</span>
              <button
                onClick={openExplore}
                className="flex items-center gap-1 text-foreground font-medium capitalize hover:opacity-70 transition-opacity cursor-pointer"
              >
                {meta?.name || name}
                <svg className="w-3 h-3 text-muted-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </button>
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
                  <div className="relative">
                    <button
                      onClick={() => {
                        if (!shareOpen) {
                          setShareOpen(true);
                          setShareTitle(messages.find((m) => m.role === "user")?.content?.slice(0, 100) || "");
                          setShareAudience("public");
                          setShareUrl(null);
                          setShareLoading(false);
                          setShareCopied(false);
                        } else {
                          setShareOpen(false);
                        }
                      }}
                      className="text-muted-foreground hover:text-foreground hover:bg-secondary/80 rounded-lg p-2 transition-colors cursor-pointer"
                      aria-label="Share"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                      </svg>
                    </button>
                    <Popover open={shareOpen} onClose={() => setShareOpen(false)} className="right-2 top-12 mt-2 w-80 max-w-[calc(100vw-1rem)] rounded-lg border border-border bg-background shadow-lg overflow-hidden">
                      <div className="px-4 pt-4 pb-3">
                            <div className="flex items-center gap-2 mb-1">
                              <svg className="w-4 h-4 text-foreground shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                              </svg>
                              <h3 className="text-sm font-medium text-foreground">{t("shareConversation")}</h3>
                            </div>
                            <div className="flex gap-1.5 mt-3 mb-3">
                              {(["public", ...(org ? [`org:${org.id}`] : [])] as string[]).map((aud) => {
                                const isOrg = aud.startsWith("org:");
                                const active = shareAudience === aud;
                                return (
                                  <button
                                    key={aud}
                                    onClick={() => setShareAudience(aud)}
                                    className={`text-[11px] px-2.5 py-1 rounded-full transition-colors cursor-pointer ${
                                      active
                                        ? "bg-secondary text-foreground"
                                        : "text-muted-foreground hover:bg-secondary/50"
                                    }`}
                                  >
                                    {isOrg ? `${t("anyoneInOrg")} ${org!.name}` : t("anyoneWithLink")}
                                  </button>
                                );
                              })}
                            </div>
                            <p className="mb-1 text-[8px] font-medium uppercase tracking-wider text-muted-foreground/40">{t("title")}</p>
                            <input
                              type="text"
                              value={shareTitle}
                              onChange={(e) => setShareTitle(e.target.value)}
                              placeholder={t("untitled")}
                              dir="auto"
                              className="w-full rounded-md border border-border bg-secondary/50 px-2.5 py-1.5 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none"
                            />
                          </div>

                          <div className="border-t border-border px-4 py-3">
                            {shareLoading ? (
                              <div className="flex items-center justify-center py-2">
                                <svg className="w-4 h-4 animate-spin text-muted-foreground" viewBox="0 0 24 24" fill="none">
                                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
                                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                                </svg>
                                <span className="ml-2 text-xs text-muted-foreground">{t("creatingLink")}</span>
                              </div>
                            ) : shareUrl ? (
                              <div className="flex items-center gap-2">
                                <input
                                  type="text"
                                  readOnly
                                  value={shareUrl}
                                  className="flex-1 min-w-0 rounded-md border border-border bg-secondary/50 px-2.5 py-1.5 text-xs text-foreground select-all focus:outline-none"
                                  onFocus={(e) => e.target.select()}
                                />
                                <button
                                  onClick={() => {
                                    navigator.clipboard.writeText(shareUrl);
                                    setShareCopied(true);
                                    setTimeout(() => setShareCopied(false), 2000);
                                  }}
                                  className="shrink-0 text-muted-foreground hover:text-foreground transition-colors cursor-pointer p-1.5"
                                  aria-label="Copy"
                                >
                                  {shareCopied ? (
                                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                                    </svg>
                                  ) : (
                                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                                    </svg>
                                  )}
                                </button>
                              </div>
                            ) : (
                              <button
                                onClick={() => {
                                  setShareLoading(true);
                                  setShareCopied(false);
                                  onShare(shareTitle, shareAudience).then((url) => {
                                    setShareUrl(url);
                                    setShareLoading(false);
                                  }).catch(() => setShareLoading(false));
                                }}
                                className="w-full rounded-md border border-border bg-secondary hover:bg-secondary/80 text-foreground py-2 text-xs font-medium transition-colors cursor-pointer"
                              >
                                {t("createLink")}
                              </button>
                            )}
                          </div>

                      {onListShares && (
                        <div className="border-t border-border">
                          <button
                            onClick={() => {
                              setShareOpen(false);
                              setFilesTab("shares");
                              setFilesOpen(true);
                              setSharesLoading(true);
                              onListShares().then((items) => {
                                setShares(items);
                                setSharesLoading(false);
                              }).catch(() => setSharesLoading(false));
                            }}
                            className="flex w-full items-center justify-between px-4 py-2.5 text-xs text-muted-foreground hover:text-foreground hover:bg-secondary/50 transition-colors cursor-pointer"
                          >
                            {t("manageShares")}
                            <svg className="w-3.5 h-3.5 rtl:rotate-180" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                            </svg>
                          </button>
                        </div>
                      )}
                    </Popover>
                  </div>
                )}
              </>
            )}
            {!user && (
              <>
                <button
                  onClick={() => toggleDark("header")}
                  className="text-muted-foreground hover:text-foreground hover:bg-secondary/80 rounded-lg p-2 transition-colors cursor-pointer"
                  aria-label="Toggle theme"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
                  </svg>
                </button>
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
            {(files || onListChats) && (
              <button
                onClick={() => {
                  setFilesOpen(!filesOpen);
                  if (!filesOpen) {
                    if (onListChats) {
                      setFilesTab("chats");
                      setChatsLoading(true);
                      onListChats().then((items) => { setChats(items); setChatsLoading(false); }).catch(() => setChatsLoading(false));
                    } else if (files) {
                      setFilesTab("files");
                      files.onNavigate(files.path);
                    }
                  }
                }}
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
                      <div className="size-8 shrink-0 rounded-md overflow-hidden" dangerouslySetInnerHTML={{ __html: agent.icon_svg }} />
                    ) : (
                      <div className="size-8 shrink-0 rounded-md bg-secondary" />
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

      {/* Spacer for fixed header */}
      <div className="shrink-0 h-12" />

      {/* Stable file input — lives outside LayoutGroup so it survives remounts */}
      {uploadFile && (
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
      )}

      <LayoutGroup>
        <LoadingBar active={chatLoading} />
        {isEmpty ? (
          <div className="flex-1 flex flex-col items-center justify-center px-6 pb-16 pt-40 sm:pt-0">
            <div className="relative max-w-3xl w-full">
              {meta && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: 0.4 }}
                  className="absolute bottom-full left-0 right-0 flex flex-col items-center gap-4 mb-10 text-center"
                >
                  {meta.logo && <div className="size-16 rounded-xl overflow-hidden border border-border" dangerouslySetInnerHTML={{ __html: meta.logo }} />}
                  <h2 className="text-2xl font-semibold text-foreground">{meta.name}</h2>
                  {meta.description && <p className="text-base text-muted-foreground max-w-lg">{meta.description}</p>}
                </motion.div>
              )}
              <InputBox {...inputProps} />
              <div className="relative">
                <div className="absolute inset-x-0 top-0">
                  <Suggestions
                    onSelect={(text) => handleSubmit(text, "suggestion")}
                    onPreview={(text) => setInput(text)}
                    input={input}
                  />
                </div>
              </div>
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
        )}
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
              className="fixed top-1 right-1 bottom-1 z-50 w-[calc(100%-0.5rem)] sm:w-[480px] rounded-xl border border-border bg-background flex flex-col overflow-hidden"
            >
              {/* Tab bar */}
              {(files || onListShares || onListChats) && (
                <div className="flex items-center border-b border-border px-4 sm:px-6">
                  {onListChats && (
                    <button
                      onClick={() => {
                        setFilesTab("chats");
                        setChatsLoading(true);
                        onListChats().then((items) => { setChats(items); setChatsLoading(false); }).catch(() => setChatsLoading(false));
                      }}
                      className={`px-3 py-3 text-sm font-medium border-b-2 transition-colors cursor-pointer ${filesTab === "chats" ? "border-foreground text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`}
                    >
                      {t("chats")}
                    </button>
                  )}
                  {files && (
                    <button
                      onClick={() => { setFilesTab("files"); files.onNavigate(files.path); }}
                      className={`px-3 py-3 text-sm font-medium border-b-2 transition-colors cursor-pointer ${filesTab === "files" ? "border-foreground text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`}
                    >
                      {t("files")}
                    </button>
                  )}
                  {onListShares && (
                    <button
                      onClick={() => {
                        setFilesTab("shares");
                        setSharesLoading(true);
                        onListShares().then((items) => { setShares(items); setSharesLoading(false); }).catch(() => setSharesLoading(false));
                      }}
                      className={`px-3 py-3 text-sm font-medium border-b-2 transition-colors cursor-pointer ${filesTab === "shares" ? "border-foreground text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`}
                    >
                      {t("shares")}
                    </button>
                  )}
                  <div className="flex-1" />
                  <button
                    onClick={() => setFilesOpen(false)}
                    className="flex size-8 items-center justify-center rounded-lg text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
                    aria-label="Close"
                  >
                    <svg className="size-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
              )}
              {filesTab === "files" && files ? (
                <Files {...files} />
              ) : filesTab === "shares" ? (
                <div className="flex h-full flex-col">
                  <div className="flex-1 overflow-y-auto">
                    {sharesLoading ? (
                      <LoadingBar />
                    ) : shares.length === 0 ? (
                      <EmptyState
                        icon={<svg className="size-full" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" /></svg>}
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
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div className="px-6 pb-5 overflow-y-auto">
              <PricingCards payerType={pricingFor} onSelect={() => closePricing("select")} />
            </div>
          </div>
        </Popover>
      )}
    </div>
  );
}


function InputBox({
  textareaRef,
  input,
  setInput,
  handleKeyDown,
  handleSubmit,
  isStreaming,
  onStop,
  onOpenFilePicker,
  onOpenFiles,
  attachments,
  onRemoveFile,
  listening,
  transcribing,
  startMic,
  stopMic,
  cancelMic,
  voice,
  onFilesAdded,
  placeholder,
}: {
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
  input: string;
  setInput: (v: string) => void;
  handleKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  handleSubmit: (overrideText?: string) => void;
  isStreaming: boolean;
  onStop: () => void;
  onOpenFilePicker?: () => void;
  onOpenFiles?: () => void;
  attachments?: Attachment[];
  onRemoveFile?: (index: number) => void;
  listening: boolean;
  transcribing: boolean;
  startMic: () => void;
  stopMic: () => void;
  cancelMic: () => void;
  voice?: boolean;
  onFilesAdded?: (files: File[]) => void;
  placeholder?: string;
}) {
  const [dragOver, setDragOver] = useState(false);

  return (
    <motion.div
      layoutId="chat-input"
      className={`border bg-background rounded-3xl p-2 shadow-sm cursor-text ${dragOver ? "border-primary" : "border-border"}`}
      onClick={() => textareaRef.current?.focus()}
      transition={{ type: "spring", stiffness: 200, damping: 25 }}
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        if (onFilesAdded && e.dataTransfer.files.length) {
          onFilesAdded(Array.from(e.dataTransfer.files));
        }
      }}
    >
      {/* File previews */}
      <AnimatePresence initial={false}>
        {attachments && attachments.length > 0 && (
          <motion.div
            key="files-list"
            initial={{ height: 0 }}
            animate={{ height: "auto" }}
            exit={{ height: 0 }}
            transition={{ type: "spring", duration: 0.2, bounce: 0 }}
            className="overflow-hidden"
          >
            <div className="flex flex-row overflow-x-auto px-2 pt-3 pb-2 gap-2">
              <AnimatePresence initial={false}>
                {attachments.map((file, index) => (
                  <motion.div
                    key={file.name + index}
                    initial={{ width: 0, opacity: 0 }}
                    animate={{ width: 180, opacity: 1 }}
                    exit={{ width: 0, opacity: 0 }}
                    transition={{ type: "spring", duration: 0.2, bounce: 0 }}
                    className="relative shrink-0"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <div className={`flex w-full items-center gap-3 rounded-2xl p-2 pr-3 transition-colors border ${file.status === "error" ? "border-red-400/60 bg-red-50 dark:bg-red-950/20" : "border-border bg-background hover:bg-secondary/50"}`}>
                      <div className="bg-secondary flex size-10 shrink-0 items-center justify-center overflow-hidden rounded-lg relative">
                        {file.type.startsWith("image/") ? (
                          <img
                            src={file.url}
                            alt={file.name}
                            className={`size-full object-cover ${file.status === "uploading" ? "opacity-40" : ""}`}
                          />
                        ) : (
                          <span className={`text-[10px] font-medium uppercase ${file.status === "error" ? "text-red-500" : "text-muted-foreground"}`}>
                            {file.name.split(".").pop()}
                          </span>
                        )}
                        {file.status === "uploading" && (
                          <div className="absolute inset-0 flex items-center justify-center">
                            <svg className="size-5 animate-spin text-muted-foreground" viewBox="0 0 24 24" fill="none">
                              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
                              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                            </svg>
                          </div>
                        )}
                      </div>
                      <div className="flex flex-col overflow-hidden min-w-0">
                        <span className={`truncate text-xs font-medium ${file.status === "error" ? "text-red-600 dark:text-red-400" : "text-foreground"}`}>{file.name}</span>
                        <span className={`text-xs ${file.status === "error" ? "text-red-500 dark:text-red-400" : "text-muted-foreground"}`}>
                          {file.status === "error" ? "Upload failed" : (file.size / 1024).toFixed(1) + " kB"}
                        </span>
                      </div>
                    </div>
                    {onRemoveFile && (
                      <button
                        type="button"
                        onClick={() => onRemoveFile(index)}
                        className="absolute top-0 right-0 z-10 flex size-5 translate-x-1/4 -translate-y-1/4 items-center justify-center rounded-full border-2 border-background bg-foreground text-background transition cursor-pointer"
                        aria-label="Remove file"
                      >
                        <svg className="size-3" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                        </svg>
                      </button>
                    )}
                  </motion.div>
                ))}
              </AnimatePresence>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Textarea */}
      <textarea
        ref={textareaRef}
        dir={input ? "auto" : getLang() === "ar" ? "rtl" : "ltr"}
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder || t("sendMessage")}
        rows={1}
        className="w-full min-h-[44px] max-h-[240px] resize-none bg-transparent px-3 py-2.5 text-foreground placeholder:text-muted-foreground focus:outline-none overflow-y-auto"
      />

      {/* Actions row: paperclip left, send right */}
      <div className="flex items-center justify-between px-1 pt-1" dir="ltr">
        <div className="relative flex items-center gap-0.5">
          {(onOpenFilePicker || onOpenFiles) && (
            <AttachMenu onOpenFilePicker={onOpenFilePicker} onOpenFiles={onOpenFiles} disabled={isStreaming} />
          )}
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              const next = getLang() === "en" ? "ar" : "en";
              setLang(next);
              track("language_changed", { to: next, source: "composer" });
            }}
            className="flex h-8 items-center justify-center rounded-full px-2.5 text-muted-foreground hover:text-foreground hover:bg-secondary transition cursor-pointer text-xs font-semibold"
            aria-label="Toggle language"
          >
            {getLang() === "en" ? "عربي" : "En"}
          </button>
        </div>
        <div className="flex items-center gap-1">
          {voice && <MicButton listening={listening} transcribing={transcribing} disabled={isStreaming} onStart={startMic} onStop={stopMic} onCancel={cancelMic}  />}
          {isStreaming ? (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onStop(); }}
              className="flex size-8 items-center justify-center rounded-full bg-foreground text-background hover:opacity-80 transition cursor-pointer"
              aria-label="Stop"
            >
              <svg className="size-5" viewBox="0 0 24 24" fill="currentColor">
                <rect x="6" y="6" width="12" height="12" rx="2" />
              </svg>
            </button>
          ) : (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); handleSubmit(); }}
              disabled={!input.trim() || attachments?.some((a) => a.status === "uploading")}
              className="flex size-8 items-center justify-center rounded-full bg-foreground text-background hover:opacity-80 disabled:opacity-30 transition cursor-pointer"
              aria-label="Send"
            >
              {/* ArrowUp */}
              <svg className="size-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 12l7-7 7 7M12 5v14" />
              </svg>
            </button>
          )}
        </div>
      </div>
    </motion.div>
  );
}

function MicButton({ listening, transcribing, disabled, onStart, onStop, onCancel }: { listening: boolean; transcribing: boolean; disabled: boolean; onStart: () => void; onStop: () => void; onCancel: () => void }) {
  return (
    <button
      type="button"
      onClick={(e) => { e.stopPropagation(); transcribing ? onCancel() : listening ? onStop() : onStart(); }}
      disabled={disabled && !transcribing}
      className={`flex size-8 items-center justify-center rounded-full transition ${disabled && !listening && !transcribing ? "text-muted-foreground opacity-30 cursor-not-allowed" : listening ? "bg-foreground text-background animate-pulse cursor-pointer" : transcribing ? "text-muted-foreground hover:text-foreground cursor-pointer" : "text-muted-foreground hover:text-foreground hover:bg-secondary cursor-pointer"}`}
      aria-label={listening ? "Stop recording" : transcribing ? "Cancel transcription" : "Start recording"}
    >
      <svg className={`size-5${transcribing ? " animate-pulse [animation-duration:0.9s]" : ""}`} fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3z" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M19 10v2a7 7 0 01-14 0v-2" />
        <line x1="12" y1="19" x2="12" y2="23" strokeLinecap="round" />
        <line x1="8" y1="23" x2="16" y2="23" strokeLinecap="round" />
      </svg>
    </button>
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

function ChatsPanel({ chats, loading, activeId, onLoad, onDelete }: {
  chats: { id: string; title: string; updatedAt: string }[];
  loading: boolean;
  activeId?: string | null;
  onLoad: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  if (loading) return <LoadingBar />;

  if (chats.length === 0) {
    return (
      <EmptyState
        icon={<svg className="size-full" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25H12" /></svg>}
        title={t("noChats")}
        subtitle={t("noChatsSub")}
      />
    );
  }

  return (
    <div className="flex-1 overflow-y-auto divide-y divide-border">
      {chats.map((s) => (
        <div
          key={s.id}
          className={`group flex items-center gap-3 px-4 py-2.5 sm:px-6 hover:bg-secondary/50 transition-colors cursor-pointer ${activeId === s.id ? "bg-secondary/30" : ""}`}
          onClick={() => onLoad(s.id)}
        >
          <div className="bg-secondary flex size-8 shrink-0 items-center justify-center rounded-lg">
            <svg className="size-4 text-muted-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25H12" />
            </svg>
          </div>
          <span className="flex-1 min-w-0 text-sm text-foreground truncate">{s.title || t("untitled")}</span>
          <span className="hidden sm:block text-xs text-muted-foreground shrink-0 w-16 text-right">
            {s.updatedAt ? formatShortDate(s.updatedAt) : ""}
          </span>
          <button
            onClick={(e) => { e.stopPropagation(); onDelete(s.id); }}
            className="flex size-7 items-center justify-center rounded-md text-muted-foreground sm:opacity-0 sm:group-hover:opacity-100 hover:text-red-500 hover:bg-red-500/10 transition-all cursor-pointer"
            aria-label="Delete chat"
          >
            <svg className="size-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24" strokeLinecap="round">
              <circle cx="12" cy="12" r="9" strokeWidth={1.5} />
              <path d="M8 12h8" />
            </svg>
          </button>
        </div>
      ))}
    </div>
  );
}

function AttachMenu({ onOpenFilePicker, onOpenFiles, disabled }: { onOpenFilePicker?: () => void; onOpenFiles?: () => void; disabled?: boolean }) {
  const [open, setOpen] = useState(false);

  if (onOpenFilePicker && !onOpenFiles) {
    return (
      <button
        type="button"
        onClick={(e) => { e.stopPropagation(); onOpenFilePicker(); }}
        disabled={disabled}
        className={`flex size-8 items-center justify-center rounded-2xl transition ${disabled ? "text-muted-foreground opacity-30 cursor-not-allowed" : "text-muted-foreground hover:text-foreground hover:bg-secondary/80 cursor-pointer"}`}
        aria-label="Attach file"
      >
        <svg className="size-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48" />
        </svg>
      </button>
    );
  }

  return (
    <>
      <button
        type="button"
        onClick={(e) => { e.stopPropagation(); if (!disabled) setOpen(!open); }}
        disabled={disabled}
        className={`flex size-8 items-center justify-center rounded-2xl transition ${disabled ? "text-muted-foreground opacity-30 cursor-not-allowed" : "text-muted-foreground hover:text-foreground hover:bg-secondary/80 cursor-pointer"}`}
        aria-label="Attach"
      >
        <svg className="size-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48" />
        </svg>
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute left-0 bottom-full z-50 mb-2 w-44 rounded-lg border border-border bg-background shadow-lg py-1">
            {onOpenFilePicker && (
              <button
                onClick={(e) => { e.stopPropagation(); setOpen(false); onOpenFilePicker(); }}
                className="flex w-full items-center gap-2.5 px-3 py-2 text-sm text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
              >
                <svg className="size-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
                </svg>
                {t("uploadFile")}
              </button>
            )}
            {onOpenFiles && (
              <button
                onClick={(e) => { e.stopPropagation(); setOpen(false); onOpenFiles(); }}
                className="flex w-full items-center gap-2.5 px-3 py-2 text-sm text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
              >
                <svg className="size-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.06-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z" />
                </svg>
                {t("browseFiles")}
              </button>
            )}
          </div>
        </>
      )}
    </>
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
