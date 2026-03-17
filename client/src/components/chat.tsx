import { useState, useRef, useEffect, useCallback } from "react";
import { createPortal } from "react-dom";
import { motion, LayoutGroup, AnimatePresence } from "framer-motion";
import { useStickToBottom } from "use-stick-to-bottom";
import { SignedIn } from "@clerk/clerk-react";
import { usePlans, useSubscription, CheckoutButton, SubscriptionDetailsButton } from "@clerk/clerk-react/experimental";
import { MessageBubble } from "./message";
import { Files } from "./files";
import type { Message, Attachment } from "../hooks/use-chat";
import type { FileEntry } from "../hooks/use-files";
import { t, getLang, setLang, useLang } from "../lib/i18n";
import { useSpeechRecognition } from "../hooks/use-speech";

interface PlanInfo {
  name: string;
  status: string;
  periodEnd: Date | null;
  canceledAt: Date | null;
  amount?: { amountFormatted: string; currencySymbol: string };
  planPeriod: string;
}

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
  onRetry,
  onShare,
  onListShares,
  onDeleteShare,
  onListSessions,
  onLoadSession,
  onDeleteSession,
  sessionId,
  sessionLoading,
  onSignOut,
  onManageAccount,
  onCreateOrg,
  onManageOrg,
  onSwitchOrg,
  activeOrg,
  orgs,
  plan,
  name,
  user,
  uploadFile,
  authHeaders,
  voice,
  files,
}: {
  messages: Message[];
  isStreaming: boolean;
  onSend: (text: string, attachments?: Attachment[]) => void;
  onStop: () => void;
  onClear: () => void;
  onRetry?: () => void;
  onShare?: (title: string) => Promise<string>;
  onListShares?: () => Promise<{ id: string; title: string; sharedAt: string; path: string }[]>;
  onDeleteShare?: (id: string) => Promise<void>;
  onListSessions?: () => Promise<{ id: string; title: string; updatedAt: string }[]>;
  onLoadSession?: (id: string) => Promise<void>;
  onDeleteSession?: (id: string) => Promise<void>;
  sessionId?: string | null;
  sessionLoading?: boolean;
  onSignOut?: () => void;
  onManageAccount?: () => void;
  onCreateOrg?: () => void;
  onManageOrg?: () => void;
  onSwitchOrg?: (orgId: string | null) => void;
  activeOrg?: { id: string; name: string; imageUrl?: string };
  orgs?: { id: string; name: string; imageUrl: string }[];
  plan?: PlanInfo;
  name?: string;
  user?: UserInfo;
  uploadFile?: (file: File) => Promise<Attachment>;
  authHeaders?: () => Promise<Record<string, string>>;
  voice?: boolean;
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
  };
}) {
  useLang();
  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [filesOpen, setFilesOpen] = useState(false);
  const [filesTab, setFilesTab] = useState<"files" | "shares" | "sessions">("files");
  const [shareOpen, setShareOpen] = useState(false);
  const [shareTitle, setShareTitle] = useState("");
  const [shareUrl, setShareUrl] = useState<string | null>(null);
  const [shareLoading, setShareLoading] = useState(false);
  const [shareCopied, setShareCopied] = useState(false);
  const [shares, setShares] = useState<{ id: string; title: string; sharedAt: string; path: string }[]>([]);
  const [sharesLoading, setSharesLoading] = useState(false);
  const [sessions, setSessions] = useState<{ id: string; title: string; updatedAt: string }[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { scrollRef, contentRef, scrollToBottom } = useStickToBottom();

  const handleSubmitRef = useRef<(overrideText?: string) => void>(() => {});

  const onSpeechEnd = useCallback((text: string) => {
    if (text.trim()) {
      handleSubmitRef.current(text);
      textareaRef.current?.blur();
    }
  }, []);
  const { listening, transcribing, start: startMic, stop: stopMic, cancel: cancelMic } = useSpeechRecognition({ onEnd: onSpeechEnd, authHeaders });

  // Reset sidebar data when org changes
  useEffect(() => {
    setSessions([]);
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

  const handleSubmit = useCallback((overrideText?: string) => {
    const text = (overrideText ?? input).trim();
    if (!text || isStreaming || attachments.some((a) => a.status === "uploading")) return;
    const sendAttachments = attachments.length > 0 ? [...attachments] : undefined;
    setInput("");
    setAttachments([]);
    onSend(text, sendAttachments);
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

  const toggleDark = () => {
    document.body.classList.toggle("dark");
  };

  return (
    <div className="h-dvh flex flex-col">
      {/* Header */}
      <header className="pointer-events-none fixed top-0 right-0 left-0 h-12" dir="ltr">
        <div className="pointer-events-auto mx-auto flex h-full max-w-full items-center justify-between px-4 sm:px-6">
          <div className="flex items-center gap-2">
          <a href="https://cycls.ai" className="flex items-center gap-2 text-foreground hover:opacity-80 transition-opacity">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 83.652 29" className="h-5 fill-muted-foreground">
              <path d="M 17.743 0.755 L 16.261 0.755 C 15.861 0.755 15.484 0.961 15.253 1.301 L 3.23 19.531 C 3.133 19.689 3.242 19.895 3.424 19.895 L 4.906 19.895 C 5.307 19.895 5.683 19.689 5.914 19.349 L 17.937 1.119 C 18.047 0.973 17.925 0.755 17.743 0.755 Z" />
              <path d="M 5.248 0 L 5.734 1.654 C 6.164 3.153 7.345 4.33 8.844 4.765 L 10.496 5.241 L 8.844 5.718 C 7.345 6.152 6.164 7.329 5.734 8.829 L 5.248 10.496 L 4.762 8.843 C 4.332 7.343 3.152 6.166 1.652 5.732 L 0 5.255 L 1.652 4.779 C 3.152 4.344 4.332 3.167 4.762 1.668 L 5.248 0 Z" />
              <path d="M 17.359 13.159 C 17.493 13.671 18.909 15.02 19.38 15.192 C 18.909 15.31 17.516 16.704 17.359 17.226 C 17.225 16.714 15.89 15.308 15.338 15.192 C 15.89 14.962 17.211 13.671 17.359 13.159 Z M 17.345 9.86 L 16.852 11.552 C 16.415 13.073 15.218 14.268 13.696 14.709 L 12.02 15.192 L 13.696 15.676 C 15.218 16.116 16.415 17.311 16.852 18.832 L 17.345 20.51 L 17.838 18.818 C 18.275 17.297 19.472 16.102 20.994 15.661 L 22.67 15.178 L 20.994 14.694 C 19.472 14.254 18.275 13.059 17.838 11.538 Z M 34.301 6.3 C 36.386 5.965 38.638 6.177 40.489 7.281 C 42.005 8.139 43.197 9.544 43.766 11.194 C 43.911 11.662 44.123 12.142 44.089 12.632 C 43.944 12.833 43.666 12.81 43.454 12.821 C 42.908 12.81 42.361 12.844 41.826 12.81 C 41.469 12.81 41.369 12.431 41.28 12.153 C 40.912 10.848 39.931 9.745 38.716 9.176 C 37.233 8.485 35.505 8.452 33.956 8.942 C 32.094 9.533 30.656 11.172 30.21 13.067 C 29.931 14.215 29.931 15.419 30.154 16.578 C 30.522 18.418 31.793 20.068 33.543 20.781 C 35.071 21.394 36.821 21.439 38.359 20.848 C 39.597 20.369 40.656 19.388 41.135 18.139 C 41.258 17.838 41.302 17.504 41.492 17.225 C 41.659 17.013 41.96 17.069 42.194 17.058 C 42.74 17.069 43.287 17.035 43.822 17.08 C 44.011 17.102 44.145 17.281 44.1 17.47 C 43.788 19.142 42.93 20.725 41.614 21.807 C 40.277 22.933 38.56 23.59 36.821 23.691 C 34.903 23.836 32.908 23.468 31.28 22.409 C 29.608 21.327 28.304 19.666 27.713 17.76 C 27.312 16.467 27.211 15.096 27.379 13.758 C 27.713 10.113 30.667 6.88 34.301 6.3 Z M 70.142 6.958 C 70.12 6.735 70.22 6.434 70.488 6.434 C 71.123 6.411 71.759 6.423 72.405 6.434 C 72.528 6.579 72.628 6.757 72.606 6.958 L 72.606 22.888 C 72.628 23.133 72.539 23.445 72.249 23.445 C 71.647 23.456 71.034 23.479 70.432 23.434 C 70.12 23.367 70.142 22.999 70.142 22.765 Z M 62.573 11.807 C 63.933 11.695 65.371 11.852 66.563 12.554 C 67.767 13.234 68.693 14.438 68.949 15.809 C 68.994 16.021 68.96 16.366 68.682 16.366 C 68.068 16.411 67.455 16.389 66.853 16.378 C 66.519 16.389 66.419 16.032 66.307 15.787 C 65.984 14.917 65.181 14.282 64.289 14.092 C 63.375 13.892 62.372 13.981 61.569 14.471 C 60.7 14.984 60.142 15.92 59.975 16.89 C 59.774 18.072 59.975 19.399 60.789 20.335 C 62.071 21.885 64.902 21.896 66.051 20.19 C 66.318 19.856 66.307 19.276 66.753 19.109 C 67.333 19.064 67.912 19.086 68.492 19.086 C 68.693 19.075 68.994 19.22 68.96 19.466 C 68.693 21.651 66.708 23.334 64.579 23.624 C 62.996 23.88 61.257 23.657 59.908 22.732 C 58.671 21.885 57.779 20.547 57.511 19.064 C 57.155 17.214 57.523 15.151 58.816 13.724 C 59.752 12.621 61.134 11.941 62.573 11.807 Z M 74.646 13 C 75.649 12.03 77.121 11.762 78.47 11.774 C 79.64 11.74 80.877 11.896 81.903 12.498 C 82.851 13.056 83.464 14.104 83.52 15.196 C 83.542 15.363 83.397 15.464 83.308 15.575 C 82.672 15.553 82.026 15.597 81.39 15.553 C 80.978 15.352 81.045 14.806 80.755 14.505 C 80.209 13.825 79.261 13.736 78.458 13.725 C 77.767 13.769 76.987 13.814 76.474 14.338 C 76.14 14.672 76.117 15.196 76.218 15.631 C 76.586 16.322 77.455 16.4 78.146 16.534 C 79.54 16.79 81.045 16.779 82.293 17.537 C 83.174 18.05 83.709 19.087 83.642 20.101 C 83.731 21.138 83.23 22.175 82.394 22.777 C 81.335 23.546 79.986 23.702 78.715 23.735 C 77.533 23.68 76.285 23.579 75.248 22.933 C 74.423 22.442 73.877 21.55 73.709 20.614 C 73.665 20.346 73.899 20.112 74.166 20.146 C 74.735 20.146 75.315 20.123 75.883 20.157 C 76.218 20.279 76.262 20.703 76.463 20.959 C 76.898 21.528 77.645 21.74 78.325 21.751 C 79.094 21.773 79.919 21.818 80.599 21.394 C 81.335 20.982 81.502 19.8 80.777 19.287 C 80.119 18.875 79.306 18.808 78.559 18.708 C 77.321 18.496 75.984 18.451 74.913 17.715 C 73.386 16.701 73.33 14.226 74.646 13 Z M 45.383 12.52 C 45.36 12.297 45.494 12.041 45.739 12.041 C 46.241 12.008 46.754 12.03 47.267 12.03 C 47.579 11.974 47.902 12.175 47.857 12.52 C 47.88 14.46 47.835 16.4 47.88 18.34 C 47.891 19.254 48.158 20.268 48.95 20.803 C 50.366 21.673 52.484 21.216 53.309 19.744 C 53.677 19.131 53.733 18.407 53.744 17.715 L 53.744 12.777 C 53.744 12.576 53.744 12.353 53.833 12.164 C 54.045 11.997 54.323 12.052 54.58 12.041 C 55.037 12.052 55.494 12.008 55.94 12.075 C 56.196 12.142 56.207 12.442 56.207 12.654 L 56.207 23.289 C 56.23 24.426 56.085 25.608 55.494 26.6 C 54.803 27.804 53.521 28.596 52.172 28.841 C 50.711 29.12 49.151 29.053 47.768 28.473 C 46.509 27.949 45.505 26.79 45.293 25.419 C 45.171 25.151 45.461 24.917 45.706 24.928 C 46.263 24.928 46.821 24.906 47.378 24.939 C 47.835 25.118 47.824 25.708 48.147 26.021 C 48.883 26.857 50.121 26.935 51.157 26.823 C 52.116 26.779 53.086 26.244 53.465 25.329 C 53.989 24.092 53.733 22.721 53.788 21.417 C 53.264 22.364 52.339 23.044 51.28 23.289 C 50.076 23.568 48.749 23.535 47.623 23 C 46.542 22.476 45.784 21.405 45.528 20.235 C 45.316 19.41 45.372 18.552 45.36 17.704 C 45.383 15.976 45.372 14.248 45.383 12.52 Z" />
            </svg>
          </a>
          {name && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span className="text-muted-foreground/40">|</span>
              <span className="text-foreground font-medium capitalize">{name}</span>
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
                    {shareOpen && createPortal(
                      <>
                        <div className="fixed inset-0 z-40" onClick={() => setShareOpen(false)} />
                        <div className="fixed right-2 top-12 z-50 mt-2 w-80 max-w-[calc(100vw-1rem)] rounded-lg border border-border bg-background shadow-lg overflow-hidden">
                          <div className="px-4 pt-4 pb-3">
                            <div className="flex items-center gap-2 mb-1">
                              <svg className="w-4 h-4 text-foreground shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                              </svg>
                              <h3 className="text-sm font-medium text-foreground">{t("shareConversation")}</h3>
                            </div>
                            <p className="text-xs text-muted-foreground">
                              {t("anyoneCanView")}
                            </p>
                            <p className="mt-3 mb-1 text-[8px] font-medium uppercase tracking-wider text-muted-foreground/40">{t("title")}</p>
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
                                  onShare(shareTitle).then((url) => {
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
                        </div>
                      </>,
                      document.body
                    )}
                  </div>
                )}
              </>
            )}
            {!user && (
              <>
                <button
                  onClick={toggleDark}
                  className="text-muted-foreground hover:text-foreground hover:bg-secondary/80 rounded-lg p-2 transition-colors cursor-pointer"
                  aria-label="Toggle theme"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
                  </svg>
                </button>
                <button
                  onClick={() => setLang(getLang() === "en" ? "ar" : "en")}
                  className="text-muted-foreground hover:text-foreground hover:bg-secondary/80 rounded-lg p-2 transition-colors cursor-pointer"
                  aria-label="Toggle language"
                >
                  <span className="text-xs font-medium w-4 h-4 flex items-center justify-center">{getLang() === "en" ? "ع" : "En"}</span>
                </button>
              </>
            )}
            {(files || onListSessions) && (
              <button
                onClick={() => {
                  setFilesOpen(!filesOpen);
                  if (!filesOpen) {
                    if (onListSessions) {
                      setFilesTab("sessions");
                      setSessionsLoading(true);
                      onListSessions().then((items) => { setSessions(items); setSessionsLoading(false); }).catch(() => setSessionsLoading(false));
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
            {user && <div className="ml-1"><UserMenu user={user} onSignOut={onSignOut} onManageAccount={onManageAccount} onCreateOrg={onCreateOrg} onManageOrg={onManageOrg} onSwitchOrg={onSwitchOrg} activeOrg={activeOrg} orgs={orgs} plan={plan} /></div>}
          </div>
        </div>
      </header>

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
        <div className="h-0.5 overflow-hidden">
          {sessionLoading && <div className="h-full w-1/3 bg-muted-foreground/30 rounded-full animate-[slide_1s_ease-in-out_infinite]" />}
        </div>
        {isEmpty ? (
          <div className="flex-1 flex flex-col items-center justify-center px-6 pb-16">
            <div className="max-w-3xl w-full">
              <InputBox
                textareaRef={textareaRef}
                input={input}
                setInput={setInput}
                handleKeyDown={handleKeyDown}
                handleSubmit={handleSubmit}
                isStreaming={isStreaming}
                onStop={onStop}
                onOpenFilePicker={uploadFile ? openFilePicker : undefined}
                onOpenFiles={files ? () => { setFilesOpen(true); setFilesTab("files"); files.onNavigate(files.path); } : undefined}
                attachments={attachments}
                onRemoveFile={removeFile}
                listening={listening}
                transcribing={transcribing}
                startMic={startMic}
                stopMic={stopMic}
                cancelMic={cancelMic}
                voice={voice}
                onFilesAdded={uploadFile ? handleFilesAdded : undefined}
              />
            </div>
          </div>
        ) : (
          <>
            <div ref={scrollRef} className="relative flex-1 overflow-y-auto" dir="ltr">
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
                <InputBox
                  textareaRef={textareaRef}
                  input={input}
                  setInput={setInput}
                  handleKeyDown={handleKeyDown}
                  handleSubmit={handleSubmit}
                  isStreaming={isStreaming}
                  onStop={onStop}
                  onOpenFilePicker={uploadFile ? openFilePicker : undefined}
                  onOpenFiles={files ? () => { setFilesOpen(true); setFilesTab("files"); files.onNavigate(files.path); } : undefined}
                  attachments={attachments}
                  onRemoveFile={removeFile}
                  listening={listening}
                  transcribing={transcribing}
                  startMic={startMic}
                  stopMic={stopMic}
                  cancelMic={cancelMic}
                  voice={voice}
                  onFilesAdded={uploadFile ? handleFilesAdded : undefined}
                />
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
              {(files || onListShares || onListSessions) && (
                <div className="flex items-center border-b border-border px-4 sm:px-6">
                  {onListSessions && (
                    <button
                      onClick={() => {
                        setFilesTab("sessions");
                        setSessionsLoading(true);
                        onListSessions().then((items) => { setSessions(items); setSessionsLoading(false); }).catch(() => setSessionsLoading(false));
                      }}
                      className={`px-3 py-3 text-sm font-medium border-b-2 transition-colors cursor-pointer ${filesTab === "sessions" ? "border-foreground text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`}
                    >
                      {t("sessions")}
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
                        {shares.map((s) => (
                          <div key={s.id} className="group relative flex items-center gap-3 px-4 py-2.5 sm:px-6 hover:bg-secondary/50 transition-colors cursor-pointer"
                            onClick={() => window.open(`/shared/${s.path}`, "_blank")}
                          >
                            <div className="bg-secondary flex size-8 shrink-0 items-center justify-center rounded-lg">
                              <svg className="size-4 text-muted-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                              </svg>
                            </div>
                            <div className="flex-1 min-w-0">
                              <span className="text-sm text-foreground truncate block">{s.title || t("untitled")}</span>
                            </div>
                            <span className="hidden sm:block text-xs text-muted-foreground shrink-0 w-16 text-right">
                              {formatShortDate(s.sharedAt)}
                            </span>
                            {onDeleteShare && (
                              <div className="relative shrink-0">
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setSharesLoading(true);
                                    onDeleteShare(s.id).then(() => {
                                      setShares((prev) => prev.filter((x) => x.id !== s.id));
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
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ) : filesTab === "sessions" ? (
                <SessionsPanel
                  sessions={sessions}
                  loading={sessionsLoading}
                  activeId={sessionId}
                  onLoad={(id) => { onLoadSession?.(id); if (window.innerWidth < 640) setFilesOpen(false); }}
                  onDelete={(id) => { setSessionsLoading(true); onDeleteSession?.(id).then(() => setSessions((prev) => prev.filter((x) => x.id !== id))).finally(() => setSessionsLoading(false)); }}
                />
              ) : null}
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </div>
  );
}

function formatPrice(money: { amount: number; currencySymbol: string; currency: string }) {
  const value = money.amount / 100;
  const formatted = new Intl.NumberFormat(getLang() === "ar" ? "ar" : "en-US", {
    style: "currency",
    currency: money.currency,
    minimumFractionDigits: value % 1 === 0 ? 0 : 2,
  }).format(value);
  return formatted;
}

function PricingCards({ payerType = "user", onSelect }: { payerType?: "user" | "organization"; onSelect: () => void }) {
  const { data: plansData, isLoading } = usePlans({ for: payerType });
  const { data: sub } = useSubscription({ for: payerType });
  const [period, setPeriod] = useState<"month" | "annual">("month");

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="size-5 border-2 border-muted-foreground/30 border-t-foreground rounded-full animate-spin" />
      </div>
    );
  }

  const plans = plansData?.filter(p => p.publiclyVisible) ?? [];
  const hasAnnual = plans.some(p => p.annualFee);
  const activePlanId = sub?.subscriptionItems?.[0]?.plan?.id;

  return (
    <div>
      {hasAnnual && (
        <div className="flex items-center justify-center gap-1 mb-4 sticky top-0 z-10 bg-background py-1 border-b border-border pb-3">
          <button
            onClick={() => setPeriod("month")}
            className={`px-3 py-1 text-xs rounded-full transition-colors cursor-pointer ${period === "month" ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground"}`}
          >
            {t("monthly")}
          </button>
          <button
            onClick={() => setPeriod("annual")}
            className={`px-3 py-1 text-xs rounded-full transition-colors cursor-pointer ${period === "annual" ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground"}`}
          >
            {t("annual")}
          </button>
        </div>
      )}
      <div className="flex flex-col sm:flex-row gap-3 sm:flex-nowrap">
        {plans.map(plan => {
          const isActive = plan.id === activePlanId;
          const price = period === "annual" && plan.annualMonthlyFee ? plan.annualMonthlyFee : plan.fee;
          const isFreePlan = !plan.hasBaseFee;
          return (
            <div
              key={plan.id}
              className={`relative flex flex-col rounded-xl border p-4 w-full sm:w-[320px] sm:shrink-0 ${isActive ? "border-muted-foreground/50 bg-muted/50" : "border-border"}`}
            >
              <div className="mb-3">
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-semibold text-foreground">{plan.name}</h3>
                  {isActive && <span className="px-1.5 py-0.5 text-[10px] font-medium rounded-full bg-muted text-muted-foreground">{t("active")}</span>}
                </div>
                {plan.description && (
                  <p className="text-xs text-muted-foreground mt-0.5">{plan.description}</p>
                )}
              </div>
              <div className="mb-4 h-12">
                {isFreePlan ? (
                  <span className="text-2xl font-bold text-foreground">{t("free")}</span>
                ) : (
                  <>
                    <div className="flex items-baseline gap-1">
                      <span className="text-2xl font-bold text-foreground">
                        {formatPrice(price)}
                      </span>
                      <span className="text-xs text-muted-foreground">{t("perMonth")}</span>
                    </div>
                    {period === "annual" && plan.annualFee ? (
                      <p className="text-[10px] text-muted-foreground mt-0.5">
                        {formatPrice(plan.annualFee)} {t("billedAnnually")}
                      </p>
                    ) : plan.freeTrialEnabled && plan.freeTrialDays ? (
                      <p className="text-[10px] text-muted-foreground mt-0.5">
                        {plan.freeTrialDays}{t("freeTrialDays")}
                      </p>
                    ) : null}
                  </>
                )}
              </div>
              {plan.features.length > 0 && (
                <ul className="mb-4 space-y-1.5 flex-1">
                  {plan.features.map(f => (
                    <li key={f.id} className="flex items-start gap-2 text-xs text-muted-foreground">
                      <svg className="w-3.5 h-3.5 mt-0.5 shrink-0 text-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                      </svg>
                      {f.name}
                    </li>
                  ))}
                </ul>
              )}
              <div className="mt-auto">
                {isActive ? (
                  <SignedIn>
                    <SubscriptionDetailsButton for={payerType}>
                      <button onClick={onSelect} className="w-full py-1.5 text-xs font-medium rounded-lg border border-border hover:bg-secondary/80 transition-colors cursor-pointer">
                        {t("managePlan")}
                      </button>
                    </SubscriptionDetailsButton>
                  </SignedIn>
                ) : (
                  <SignedIn>
                    <CheckoutButton
                      planId={plan.id}
                      planPeriod={period}
                      for={payerType}
                      onSubscriptionComplete={onSelect}
                    >
                      <button onClick={onSelect} className="w-full py-1.5 text-xs font-medium rounded-lg border border-border hover:bg-secondary/80 transition-colors cursor-pointer">
                        {isFreePlan ? t("getStarted") : t("subscribe")}
                      </button>
                    </CheckoutButton>
                  </SignedIn>
                )}
              </div>
            </div>
          );
        })}
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
  plan?: PlanInfo;
}) {
  const [open, setOpen] = useState(false);
  const [showOrgs, setShowOrgs] = useState(false);
  const [pricingFor, setPricingFor] = useState<"user" | "organization" | null>(null);
  useEffect(() => {
    const plans = new URLSearchParams(window.location.search).get("plans");
    if (!plans) return;
    window.history.replaceState({}, "", window.location.pathname);
    if (plans === "b2c") {
      setPricingFor("user");
    } else if (plans === "b2b") {
      if (activeOrg) {
        setPricingFor("organization");
      } else {
        onCreateOrg?.();
      }
    }
  }, [activeOrg, onCreateOrg]);

  return (
    <div className="relative">
      <button
        onClick={() => { setOpen(!open); setShowOrgs(false); }}
        className="flex items-center justify-center rounded-lg hover:opacity-80 transition-opacity cursor-pointer px-1 h-8"
        aria-label="Profile"
      >
        <div className="flex items-center -space-x-2">
          {activeOrg?.imageUrl && (
            <div
              className="size-6 rounded-full bg-secondary shrink-0 ring-2 ring-background"
              style={{ backgroundImage: `url(${activeOrg.imageUrl})`, backgroundSize: "cover" }}
            />
          )}
          <div
            className="size-6 rounded-full bg-secondary text-foreground flex items-center justify-center text-xs font-medium select-none ring-2 ring-background"
            style={user.imageUrl ? { backgroundImage: `url(${user.imageUrl})`, backgroundSize: "cover" } : undefined}
          >
            {!user.imageUrl && (user.name?.charAt(0) || user.email?.charAt(0) || "?")}
          </div>
        </div>
      </button>
      {open && createPortal(
        <>
          <div className="fixed inset-0 z-40" onClick={() => { setOpen(false); setShowOrgs(false); }} />
          <div className="fixed right-2 top-12 z-50 mt-2 w-56 rounded-lg border border-border bg-background shadow-lg">
            {showOrgs ? (
              <>
                <button
                  onClick={() => setShowOrgs(false)}
                  className="flex w-full items-center gap-2 px-3 py-2.5 text-sm text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
                >
                  <svg className="w-3.5 h-3.5 rtl:rotate-180" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                  </svg>
                  {t("back")}
                </button>
                <div className="border-t border-border" />
                <div className="py-1">
                  <button
                    onClick={() => { onSwitchOrg?.(null); setShowOrgs(false); }}
                    className={`flex w-full items-center gap-2 px-3 py-1.5 text-sm transition-colors cursor-pointer ${!activeOrg ? "text-foreground bg-secondary/60" : "text-muted-foreground hover:text-foreground hover:bg-secondary/80"}`}
                  >
                    {t("personal")}
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
                      {t("createOrg")}
                    </button>
                  </>
                )}
              </>
            ) : (
              <>
                <div className="flex items-center gap-2.5 px-3 py-2.5">
                  <div
                    className="size-8 rounded-full bg-secondary text-foreground flex items-center justify-center text-sm font-medium select-none shrink-0"
                    style={user.imageUrl ? { backgroundImage: `url(${user.imageUrl})`, backgroundSize: "cover" } : undefined}
                  >
                    {!user.imageUrl && (user.name?.charAt(0) || user.email?.charAt(0) || "?")}
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-foreground truncate">{user.name}</p>
                    <p className="text-xs text-muted-foreground truncate">{user.email}</p>
                  </div>
                </div>
                <div className="border-t border-border" />
                <button
                  onClick={() => document.body.classList.toggle("dark")}
                  className="flex w-full items-center gap-2 px-3 py-2.5 text-sm text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
                  </svg>
                  {document.body.classList.contains("dark") ? t("lightMode") : t("darkMode")}
                </button>
                <button
                  onClick={() => setLang(getLang() === "en" ? "ar" : "en")}
                  className="flex w-full items-center gap-2 px-3 py-2.5 text-sm text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
                >
                  {t("language")}
                </button>
                <div className="border-t border-border" />
                <p className="px-3 pt-2 pb-1 text-[8px] font-medium uppercase tracking-wider text-muted-foreground/40">{t("account")}</p>
                {plan && (
                  <button
                    onClick={() => { setOpen(false); setPricingFor(activeOrg ? "organization" : "user"); }}
                    className="flex w-full items-center justify-between px-3 py-2.5 text-sm text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
                  >
                    {t("plans")}
                    <span className="text-[10px] text-muted-foreground/60">{plan.name}</span>
                  </button>
                )}
                <button
                  onClick={() => { setOpen(false); activeOrg && onManageOrg ? onManageOrg() : onManageAccount?.(); }}
                  className="flex w-full items-center gap-2 px-3 py-2.5 text-sm text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
                >
                  {activeOrg ? t("manageOrg") : t("manageAccount")}
                </button>
                {onSwitchOrg && (
                  <>
                  <div className="border-t border-border" />
                  <p className="px-3 pt-2 pb-1 text-[8px] font-medium uppercase tracking-wider text-muted-foreground/40">{t("organization")}</p>
                  <button
                    onClick={() => setShowOrgs(true)}
                    className="flex w-full items-center justify-between px-3 py-2.5 text-sm text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
                  >
                    <span className="flex items-center gap-2 truncate">
                      {activeOrg?.imageUrl && (
                        <div className="size-4 rounded-full shrink-0" style={{ backgroundImage: `url(${activeOrg.imageUrl})`, backgroundSize: "cover" }} />
                      )}
                      {activeOrg ? activeOrg.name : t("personal")}
                    </span>
                    <svg className="w-3.5 h-3.5 rtl:rotate-180" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                    </svg>
                  </button>
                  </>
                )}
                {onSignOut && (
                  <>
                    <div className="border-t border-border" />
                    <button
                      onClick={() => { setOpen(false); onSignOut(); }}
                      className="flex w-full items-center gap-2 px-3 py-2.5 text-sm text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
                    >
                      {t("signOut")}
                    </button>
                  </>
                )}
              </>
            )}
          </div>
        </>,
        document.body
      )}
      {pricingFor && createPortal(
        <>
          <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm" onClick={() => setPricingFor(null)} />
          <div className="fixed inset-0 z-50 flex items-center justify-center pointer-events-none" dir="ltr">
            <div className="pointer-events-auto fixed top-1 right-1 bottom-1 w-[calc(100%-0.5rem)] flex flex-col rounded-xl border border-border bg-background shadow-xl sm:relative sm:inset-auto sm:w-auto sm:max-h-[90vh] sm:rounded-2xl">
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
                  onClick={() => setPricingFor(null)}
                  className="text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
              <div className="px-6 pb-5 overflow-y-auto">
                <PricingCards payerType={pricingFor} onSelect={() => setPricingFor(null)} />
              </div>
            </div>
          </div>
        </>,
        document.body
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
        placeholder={t("sendMessage")}
        rows={1}
        className="w-full min-h-[44px] max-h-[240px] resize-none bg-transparent px-3 py-2.5 text-foreground placeholder:text-muted-foreground focus:outline-none overflow-y-auto"
      />

      {/* Actions row: paperclip left, send right */}
      <div className="flex items-center justify-between px-1 pt-1">
        <div className="relative flex items-center">
          {(onOpenFilePicker || onOpenFiles) && (
            <AttachMenu onOpenFilePicker={onOpenFilePicker} onOpenFiles={onOpenFiles} disabled={isStreaming} />
          )}
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

function LoadingBar() {
  return (
    <div className="h-0.5 overflow-hidden">
      <div className="h-full w-1/3 bg-muted-foreground/30 rounded-full animate-[slide_1s_ease-in-out_infinite]" />
    </div>
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
      <svg className={`size-5${transcribing ? " animate-pulse" : ""}`} fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
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

function SessionsPanel({ sessions, loading, activeId, onLoad, onDelete }: {
  sessions: { id: string; title: string; updatedAt: string }[];
  loading: boolean;
  activeId?: string | null;
  onLoad: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  if (loading) return <LoadingBar />;

  if (sessions.length === 0) {
    return (
      <EmptyState
        icon={<svg className="size-full" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25H12" /></svg>}
        title={t("noSessions")}
        subtitle={t("noSessionsSub")}
      />
    );
  }

  return (
    <div className="flex-1 overflow-y-auto divide-y divide-border">
      {sessions.map((s) => (
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
            aria-label="Delete session"
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
