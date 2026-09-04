import { useState, useRef, useEffect, useCallback } from "react";
import { motion, LayoutGroup, AnimatePresence } from "framer-motion";
import { useStickToBottom } from "use-stick-to-bottom";
import { MessageBubble } from "./message";
import { Files, InlineInput, DropdownMenu } from "./files";
import { Canvas, type CanvasFile } from "./canvas";
import { editWorkingPath, ext } from "./canvas-utils";
import { AppsPanel } from "./apps-panel";
import { TrashView, type TrashRow } from "./trash-view";
import { useApps, type AppInfo } from "../hooks/use-apps";
import { Popover } from "./popover";
import { Icon, IconButton } from "./icon";
import { CyclsLogo } from "./cycls-logo";
import { LoadingBar } from "./loading-bar";
import { InputBox } from "./input-box";
import { ShareDialog } from "./share-dialog";
import { PricingCards } from "./pricing-cards";
import { UserMenu, type UserInfo, type PlanInfo } from "./user-menu";
import { SettingsDialog } from "./settings-dialog";
import { WorkspaceMenu, type WorkspacesMenu } from "./workspace-switcher";
import type { Attachment, ChatApi, AppConfig } from "../hooks/use-chat";
import type { FileEntry } from "../hooks/use-files";
import { t, getLang, setLang, useLang } from "../lib/i18n";
import { track } from "../lib/analytics";
import { toggleDark, cn, followUpsEnabled, askEnabled, slide } from "../lib/utils";
import { useToast } from "../lib/toast";
import { useSpeechRecognition } from "../hooks/use-speech";
import { useUrlParam } from "../hooks/use-url-param";
import { useMediaQuery } from "../hooks/use-media-query";
import { usePaneWidth } from "../hooks/use-pane-width";
import { SUGGESTIONS } from "./suggestions-data";
import { ExamplesGallery } from "./examples";
import { AskCard, type AskQuestion } from "./ask-card";
import { Surfaces } from "./surfaces";
import { SurveyStrip, useSurvey } from "./survey-strip";

export interface PassAgent {
  slug: string;
  title: string;
  title_ar?: string;
  description: string;
  description_ar?: string;
  link: string;
  icon_svg?: string;
}

type PanelTab = "files" | "shares" | "chats" | "apps" | "trash";

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
  // Re-list bypassing the server's catalog cache; use after our own writes.
  onReload: (dir: string) => void;
  onUpload: (dir: string, file: File) => Promise<void>;
  onUploadBatch?: (dir: string, files: { rel: string; file: File }[]) => Promise<void>;
  onMkdir: (dir: string, name: string) => Promise<void>;
  onRename: (from: string, to: string) => Promise<void>;
  onDelete: (path: string) => Promise<{ trash_id: string; kind: string } | void>;   // a move into the trash
  onListTrash?: () => Promise<TrashRow[]>;
  onRestoreTrash?: (id: string, kind: string, method: string) => Promise<string>;
  onPurgeTrash?: (id: string, kind: string) => Promise<void>;
  onEmptyTrash?: () => Promise<void>;
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

// A message composed while the agent was still working, waiting its turn.
interface Queued {
  id: string;
  text: string;
  attachments?: Attachment[];
  origin: string;
}

const RAIL_ICON_W = 44;   // folded rail: icon strip only

export function Chat({ chat, onShare, files, account, config }: {
  chat: ChatApi;
  onShare?: (audience: string) => Promise<string>;
  files?: FilesPanelProps;
  account?: AccountInfo | null;
  config?: AppConfig | null;
}) {
  const { messages, isStreaming, chatLoading, chatId, send: onSend, retry: onRetry, regenerate: onRegenerate, stop: onStop, clear: onClear, listShares: onListShares, deleteShare: onDeleteShare, listChats: onListChats, loadChat: onLoadChat, deleteChat: onDeleteChat, renameChat: onRenameChat, setFavorite: onSetFavorite, uploadFile, authHeaders, setUIHandler } = chat;
  const { user, plan, org, activeOrg, orgs, onSignOut, onManageAccount, onCreateOrg, onManageOrg, onSwitchOrg, workspaces } = account ?? ({} as Partial<AccountInfo>);
  const { name, pass_metadata: passMetadata, voice, suggestions, examples_enabled: examplesEnabled } = config ?? {};

  const lang = useLang();
  const { error: toastError, info: toastInfo, undo: toastUndo } = useToast();
  const isAr = lang === "ar";
  // logo and brand inherit from en; name/description stay per-locale.
  const _active = passMetadata?.[isAr ? "ar" : "en"];
  const _en = passMetadata?.en;
  const meta = _active
    ? { ..._active, logo: _active.logo || _en?.logo || "", brand: _active.brand || _en?.brand || "" }
    : _en;
  const inputPlaceholder = meta
    ? (isAr ? `اسأل ${meta.name}` : `Ask ${meta.name}`)
    : undefined;
  // A prompt drafted before sign-in (public shell, example card) survives the
  // auth round-trip here — consumed once, so later remounts start clean.
  const [input, setInput] = useState(() => {
    const draft = sessionStorage.getItem("cycls_draft");
    if (draft) sessionStorage.removeItem("cycls_draft");
    return draft || "";
  });
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [exploreOpen, setExploreOpen] = useState(false);
  const [exploreAgents, setExploreAgents] = useState<PassAgent[]>([]);
  const [exploreLoading, setExploreLoading] = useState(false);
  // Panel open state + tab survive the ChatApp remount on workspace/org
  // switch, so the panel's workspace switcher works in place.
  const [filesOpen, _setFilesOpen] = useState(() => sessionStorage.getItem("cycls_panel") === "1");
  const setFilesOpen = useCallback((v: boolean | ((p: boolean) => boolean)) => {
    _setFilesOpen((prev) => {
      const next = typeof v === "function" ? v(prev) : v;
      if (next) sessionStorage.setItem("cycls_panel", "1");
      else sessionStorage.removeItem("cycls_panel");
      return next;
    });
  }, []);
  const [filesTab, setFilesTab] = useState<PanelTab>(() =>
    (sessionStorage.getItem("cycls_panel_tab") as PanelTab) || (account ? "chats" : "files"));
  // The agent's `suggest` tool offers ONE follow-up message at a time — a
  // chip above the composer; click sends it, ArrowUp pulls it in to edit.
  const [followUp, setFollowUp] = useState<string | null>(null);
  const [followUpsOn, setFollowUpsOn] = useState(followUpsEnabled);
  // Messages composed while the agent is still working. They flush one at a
  // time when a run ends on its own; an explicit Stop *holds* the queue
  // instead, so interrupting a run that went wrong doesn't immediately fire
  // the next message into it.
  const [queued, setQueued] = useState<Queued[]>([]);
  // `queuedRef` is the source of truth every writer updates in the same tick,
  // so a click can't race the stream-end flush on a stale copy; `queued` is
  // just its rendered shadow.
  const queuedRef = useRef<Queued[]>([]);
  const heldRef = useRef(false);
  const wasStreamingRef = useRef(false);
  // The agent's `ask` tool — up to three questions on one card above the
  // composer. The options are shortcuts, not a constraint: typing any reply
  // answers it too.
  const [ask, setAsk] = useState<{ questions: AskQuestion[] } | null>(null);
  // Typing takes over: the moment the user starts composing, the agent's
  // chip and card yield — their own words beat our prompts.
  const prevInputRef = useRef(input);
  useEffect(() => {
    const started = !prevInputRef.current.trim() && !!input.trim();
    prevInputRef.current = input;
    if (!started) return;
    setFollowUp(null);
    setHushed(true);
    setAsk((cur) => {
      if (cur) track("ask_dismissed", { chat_id: chatId, method: "typed" });
      return null;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [input]);
  useEffect(() => {
    const sync = () => {
      setFollowUpsOn(followUpsEnabled());
      if (!followUpsEnabled()) setFollowUp(null);
      if (!askEnabled()) setAsk(null);
    };
    window.addEventListener("followupschange", sync);
    window.addEventListener("askchange", sync);
    return () => {
      window.removeEventListener("followupschange", sync);
      window.removeEventListener("askchange", sync);
    };
  }, []);
  useEffect(() => {
    setFollowUp(null);
    setAsk(null);
    queuedRef.current = [];
    setQueued([]);
    heldRef.current = false;
  }, [chatId]);
  // Prompts and surveys wait for a finished turn: nobody is asked anything
  // before the product has done something for them.
  const [turnsDone, setTurnsDone] = useState(0);
  const wasStreaming = useRef(false);
  useEffect(() => {
    if (wasStreaming.current && !isStreaming && messages.length) setTurnsDone((n) => n + 1);
    wasStreaming.current = isStreaming;
  }, [isStreaming, messages.length]);
  const [survey, setSurvey] = useSurvey(turnsDone > 0);
  // Typing hushes every surface — prompt, tip, survey — until the next turn.
  const [hushed, setHushed] = useState(false);
  useEffect(() => { setHushed(false); }, [turnsDone]);
  const [canvasTabs, setCanvasTabs] = useState<CanvasFile[]>([]);
  const [canvasActive, setCanvasActive] = useState<string | null>(null);
  const [canvasHidden, setCanvasHidden] = useState(false);
  const [rightExpanded, setRightExpanded] = useState(false);
  const isDesktop = useMediaQuery("(min-width: 1024px)");

  const openFileInCanvas = useCallback((path: string, name?: string, ident?: Partial<CanvasFile>) => {
    setCanvasTabs((tabs) => (tabs.some((f) => f.path === path) ? tabs
      : [...tabs, { ...ident, path, name: name || path.split("/").pop() || path }]));
    setCanvasActive(path);
    setCanvasHidden(false);
  }, []);

  // A deliverable being written opens the canvas in a working state — the
  // path arrives in the live edit step's streamed args. Desktop only.
  const [workingPaths, setWorkingPaths] = useState<string[]>([]);
  useEffect(() => {
    if (!isStreaming) { setWorkingPaths((ws) => (ws.length ? [] : ws)); return; }
    if (!isDesktop) return;
    const last = messages[messages.length - 1];
    if (last?.role !== "assistant") return;
    for (const p of last.parts || []) {
      if (p.type !== "step" || p.tool_name !== "Editing") continue;
      const path = editWorkingPath(p.step, p.args);
      if (path && !workingPaths.includes(path)) {
        setWorkingPaths((ws) => (ws.includes(path) ? ws : [...ws, path]));
        openFileInCanvas(path);
        track("canvas_loader_shown", { path });
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages, isStreaming, isDesktop]);
  const closeCanvasTab = useCallback((path: string) => {
    setCanvasTabs((tabs) => tabs.filter((f) => f.path !== path));
    setCanvasActive((a) => (a === path ? null : a));
  }, []);
  const { apps, loading: appsLoading, refresh: refreshApps } = useApps();
  // The UI handler resolves an app by path without re-subscribing on every load.
  const appsRef = useRef<AppInfo[]>([]);
  useEffect(() => { appsRef.current = apps; }, [apps]);
  const openApp = useCallback((app: AppInfo) => {
    openFileInCanvas(app.entry, app.name, {
      icon: app.icon, iconSrc: app.iconSrc, letter: app.letter,
    });
  }, [openFileInCanvas]);
  const { width: panelWidth, startResize, resizing: railResizing } = usePaneWidth("cycls_rail_width", 320, 240, 80, 0,
    () => canvasShowing && setRailIcons(true), 0.5);
  const [shareOpen, setShareOpen] = useState(false);
  // Survives the ChatApp remount on org/workspace switch (App keys by org), so
  // changing context inside the settings dialog doesn't close it.
  const [settingsOpen, _setSettingsOpen] = useState(() => sessionStorage.getItem("cycls_settings") === "1");
  const setSettingsOpen = useCallback((v: boolean) => {
    _setSettingsOpen(v);
    if (v) sessionStorage.setItem("cycls_settings", "1");
    else sessionStorage.removeItem("cycls_settings");
  }, []);
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
        // The agent blocked the user — a paywall, not a curious plans click.
        track("paywall_shown", { reason: ev.reason || "unspecified" });
        if (ev.reason === "limit") track("limit_reached", {});
        openPricing(activeOrg ? "organization" : "user", "agent_event");
      } else if (ev.action === "open_canvas" && typeof ev.path === "string") {
        const done = ev.path;
        track("artifact_completed", { path: done, kind: ext(done) });
        setWorkingPaths((ws) => ws.filter((x) => x !== done));
        const app = appsRef.current.find((a) => a.entry === ev.path);
        if (app) openApp(app);
        else openFileInCanvas(ev.path, typeof ev.name === "string" ? ev.name : undefined);
      } else if (ev.action === "suggest" && typeof ev.text === "string") {
        if (followUpsEnabled()) {
          setFollowUp(ev.text);
          track("ui_action", { action: "suggest" });   // denominator for followup_accepted
        }
      } else if (ev.action === "ask") {
        // The flat singular keys are the same event's back-compat tail.
        const raw = Array.isArray(ev.questions) ? ev.questions
                  : typeof ev.question === "string" ? [ev] : [];
        const questions = (raw as Record<string, unknown>[])
          .filter((q) => q && typeof q.question === "string")
          .map((q) => {
            const options = Array.isArray(q.options)
              ? (q.options as { label?: unknown; description?: unknown }[])
                  .filter((o) => o && typeof o.label === "string")
                  .map((o) => ({ label: o.label as string,
                                 description: typeof o.description === "string" ? o.description : undefined }))
              : [];
            return { question: q.question as string,
                     header: typeof q.header === "string" ? q.header : undefined,
                     options, multi: q.multi_select === true && options.length > 1 };
          });
        if (questions.length && askEnabled()) {
          setAsk({ questions });
          track("ui_action", { action: "ask", questions: questions.length });
        }
      } else {
        track("ui_action", { action: ev.action, handled: false });
      }
    });
    return () => setUIHandler(null);
  }, [setUIHandler, activeOrg, openPricing, openFileInCanvas, openApp]);

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
    if (!text || attachments.some((a) => a.status === "uploading")) return;
    const sendAttachments = attachments.length > 0 ? [...attachments] : undefined;
    setInput("");
    setAttachments([]);
    setFollowUp(null);
    setAsk(null);
    // Sending mid-run queues instead: the agent's tool loops are long, and a
    // thought the user has now shouldn't wait on them.
    if (isStreaming) {
      const next = [...queuedRef.current,
                    { id: crypto.randomUUID(), text, attachments: sendAttachments, origin }];
      queuedRef.current = next;
      setQueued(next);
      track("message_queued", { chat_id: chatId, origin, queue_depth: next.length });
      return;
    }
    heldRef.current = false;
    onSend(text, sendAttachments, origin);
    setTimeout(() => scrollToBottom(), 0);
  }, [input, isStreaming, onSend, attachments, scrollToBottom, chatId]);

  // Drain on the falling edge of `isStreaming` — one message per edge, and the
  // send it triggers raises the flag again, so the rest follow in order.
  useEffect(() => {
    const ended = wasStreamingRef.current && !isStreaming;
    wasStreamingRef.current = isStreaming;
    if (!ended || heldRef.current) return;
    const [next, ...rest] = queuedRef.current;
    if (!next) return;
    queuedRef.current = rest;
    setQueued(rest);
    track("queued_message_sent", { chat_id: chatId, remaining: rest.length });
    onSend(next.text, next.attachments, "queued");
    setTimeout(() => scrollToBottom(), 0);
  }, [isStreaming, onSend, scrollToBottom, chatId]);

  // Stop holds the queue rather than draining into a run the user just killed.
  const handleStop = useCallback(() => {
    heldRef.current = true;
    onStop();
  }, [onStop]);

  // Pull a queued message back into the composer for editing — the same
  // gesture as accepting a follow-up, and the only way to send one while the
  // queue is held.
  const editQueued = useCallback((id: string) => {
    const hit = queuedRef.current.find((m) => m.id === id);
    if (!hit) return;
    queuedRef.current = queuedRef.current.filter((m) => m.id !== id);
    setQueued(queuedRef.current);
    setInput((cur) => (cur ? `${cur} ${hit.text}` : hit.text));
    if (hit.attachments?.length) setAttachments((cur) => [...cur, ...hit.attachments!]);
    requestAnimationFrame(() => textareaRef.current?.focus());
    track("queued_message_edited", { chat_id: chatId });
  }, [chatId]);

  const dropQueued = useCallback((id: string) => {
    queuedRef.current = queuedRef.current.filter((m) => m.id !== id);
    setQueued(queuedRef.current);
    track("queued_message_dropped", { chat_id: chatId });
  }, [chatId]);

  handleSubmitRef.current = handleSubmit;

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    const isMobile = window.matchMedia("(pointer: coarse)").matches;
    if (e.key === "Enter" && !e.shiftKey && !isMobile) {
      e.preventDefault();
      handleSubmit();
    }
    // Shell-style accept: ArrowUp in an empty composer pulls the suggested
    // follow-up in for editing; Enter then sends it.
    if (e.key === "ArrowUp" && !input && followUp) {
      e.preventDefault();
      setInput(followUp);
      setFollowUp(null);
      track("followup_accepted", { method: "arrow" });
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
  const selectTab = (tab: PanelTab) => {
    setFilesTab(tab);
    sessionStorage.setItem("cycls_panel_tab", tab);
    if (tab === "chats" && onListChats) {
      setChatsLoading(true);
      onListChats().then((items) => { setChats(items); setChatsLoading(false); }).catch(() => setChatsLoading(false));
    } else if (tab === "shares" && onListShares) {
      setSharesLoading(true);
      onListShares().then((items) => { setShares(items); setSharesLoading(false); }).catch(() => setSharesLoading(false));
    } else if (tab === "files" && files) {
      files.onNavigate(files.path);
      loadTrash();   // footer count; listing is also the 30-day sweep
    } else if (tab === "trash") {
      loadTrash();
    }
  };

  // Open the panel, keeping the last-active tab unless one is given.
  const openPanel = (tab?: PanelTab) => {
    selectTab(tab ?? filesTab);
    setFilesOpen(true);
  };

  // Restored-open panel (workspace/org switch remounts Chat): load the
  // active tab's data, same as the click path would have.
  useEffect(() => {
    if (filesOpen) selectTab(filesTab);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- Trash: deletes are moves; Undo (toast or ⌘Z, 10s) restores the last one ----
  const [trashRows, setTrashRows] = useState<TrashRow[]>([]);
  const [trashLoading, setTrashLoading] = useState(false);
  const [trashFilter, setTrashFilter] = useState<"chat" | undefined>(undefined);
  const loadTrash = useCallback(() => {
    if (!files?.onListTrash) return;
    setTrashLoading(true);
    files.onListTrash().then(setTrashRows).catch(() => {}).finally(() => setTrashLoading(false));
  }, [files]);
  const wsMenu = account?.workspaces;
  const canPurge = !wsMenu || !wsMenu.active || ["owner", "admin"].includes(wsMenu.active.role || "") || !!wsMenu.isOrgAdmin;
  const undoRef = useRef<{ id: string; kind: string; name: string; at: number }[]>([]);
  const afterRestore = useCallback((kind: string) => {
    if (kind === "chat") { if (onListChats) onListChats().then(setChats).catch(() => {}); }
    else if (files) { files.onReload(files.path); if (kind === "app") void refreshApps(); }
    loadTrash();
  }, [files, onListChats, refreshApps, loadTrash]);
  const undoLast = useCallback((method: string) => {
    const last = undoRef.current.pop();
    if (!last || !files?.onRestoreTrash) return;
    files.onRestoreTrash(last.id, last.kind, method)
      .then(() => { toastInfo(t("restored").replace("{name}", last.name)); afterRestore(last.kind); })
      .catch(() => toastError(t("restoreFailed")));
  }, [files, toastInfo, toastError, afterRestore]);
  const trashed = useCallback((id: string, kind: string, name: string) => {
    undoRef.current.push({ id, kind, name, at: Date.now() });
    toastUndo(t("deleted").replace("{name}", name), t("undo"), () => undoLast("toast"));
  }, [toastUndo, undoLast]);
  const deleteWithUndo = useCallback(async (path: string) => {
    const r = await files!.onDelete(path);
    if (r && r.trash_id) trashed(r.trash_id, r.kind, path.split("/").pop() || path);
    return r;
  }, [files, trashed]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.key.toLowerCase() !== "z" || e.shiftKey) return;
      const el = document.activeElement as HTMLElement | null;
      const tag = (el?.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea" || el?.isContentEditable) return;   // native text undo
      const last = undoRef.current[undoRef.current.length - 1];
      if (!last || Date.now() - last.at > 10_000) return;
      e.preventDefault();
      undoLast("shortcut");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [undoLast]);

  // App identity lives in its manifest; the slug (folder) stays immutable.
  const updateApp = useCallback(async (app: AppInfo, patch: { name?: string; icon?: string }) => {
    if (!files) return;
    const path = `apps/${app.slug}/app.json`;
    let manifest: Record<string, unknown> = {};
    try { manifest = JSON.parse(await files.readFile(path)); } catch { manifest = {}; }
    const next: Record<string, unknown> = { ...manifest, ...patch };
    if (patch.icon === "") delete next.icon;
    await files.writeFile(path, JSON.stringify(next, null, 2));
    track("app_updated", { field: Object.keys(patch)[0] });
    await refreshApps();
  }, [files, refreshApps]);

  // An image icon lives beside the app as `icon.<ext>`; the manifest names it.
  const uploadAppIcon = useCallback(async (app: AppInfo, file: File) => {
    if (!files) return;
    const ext = (file.name.match(/\.(png|jpe?g|svg|webp|gif|avif)$/i)?.[1] ?? "png").toLowerCase();
    if (file.size > 2 * 1024 * 1024) { toastError(t("iconTooLarge")); return; }
    await files.onUpload(`apps/${app.slug}`, new File([file], `icon.${ext}`, { type: file.type }));
    await updateApp(app, { icon: `icon.${ext}` });
  }, [files, updateApp, toastError]);

  const canvasShowing = canvasTabs.length > 0 && !canvasHidden;
  const rightOpen = filesOpen || canvasShowing;
  const [railIcons, setRailIcons] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  useEffect(() => { if (!isStreaming) setReloadKey((k) => k + 1); }, [isStreaming]);
  const railIconsOnly = isDesktop && railIcons && canvasShowing;
  const railPx = !isDesktop || !filesOpen ? 0 : railIconsOnly ? RAIL_ICON_W : panelWidth;
  const collapseRail = () => (canvasShowing ? setRailIcons(true) : setFilesOpen(false));
  const closeRight = () => {
    setFilesOpen(false);
    setCanvasHidden(true);
    setRightExpanded(false);
    setRailIcons(false);
  };
  useEffect(() => {
    if (!rightOpen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") closeRight(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const openRight = () => {
    setRailIcons(false);
    if (canvasTabs.length > 0) setCanvasHidden(false);
    if (!canvasTabs.length || !filesOpen) openPanel();
  };

  const inputProps = {
    textareaRef, input, setInput, handleKeyDown, handleSubmit, isStreaming, onStop: handleStop,
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
            {/* Desktop only; on a phone it stays a row inside the user menu */}
            {user && workspaces && isDesktop && <WorkspaceMenu workspaces={workspaces} />}
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
            {(files || account) && (
              <button
                onClick={() => rightOpen ? closeRight() : openRight()}
                className={`${rightOpen ? "text-foreground" : "text-muted-foreground"} hover:text-foreground hover:bg-secondary/80 rounded-lg p-2 transition-colors cursor-pointer`}
                aria-label={rightOpen ? t("collapse") : t("expand")}
                title={rightOpen ? t("collapse") : t("expand")}
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 3.75v16.5M20.25 3.75H3.75v16.5h16.5M14.25 3.75v16.5" />
                </svg>
              </button>
            )}
            {user && <div className="ml-1"><UserMenu user={user} onSignOut={onSignOut} onManageAccount={onManageAccount} onOpenSettings={account ? () => setSettingsOpen(true) : undefined} onCreateOrg={onCreateOrg} onManageOrg={onManageOrg} onSwitchOrg={onSwitchOrg} activeOrg={activeOrg} orgs={orgs} plan={plan} onOpenPlans={() => openPricing(activeOrg ? "organization" : "user", "user_menu")} workspaces={isDesktop ? undefined : workspaces} /></div>}
          </div>
        </div>
      </header>
      <Surfaces config={config ?? null} ready={turnsDone > 0} active={!isStreaming && !ask && !hushed} />

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
      <div className={cn("relative flex h-full min-w-0 flex-1 flex-col", isDesktop && rightExpanded && rightOpen && "hidden")}>
      <LayoutGroup>
        <LoadingBar active={chatLoading} />
        {!chatLoading && (isEmpty ? (
          examplesEnabled ? (
            // With a gallery the empty screen is a page that scrolls: hero and
            // composer centered in the viewport, category chips and the top of
            // the cards peeking below the fold.
            <div className="flex-1 overflow-y-auto">
              <div className="mx-auto flex w-full max-w-5xl flex-col items-center px-6 pb-16">
                {/* justify-end + half-viewport height lands the composer's
                    bottom at mid-page (true center, hero above), and the
                    gallery hangs right below it. */}
                <div className="flex min-h-[calc(50dvh-2rem)] w-full flex-col items-center justify-end">
                  {meta && <EmptyHero meta={meta} />}
                  <div className="w-full max-w-3xl">
                    <InputBox {...inputProps} />
                  </div>
                </div>
                <ExamplesGallery
                  className="mt-5"
                  onUsePrompt={(text) => { setInput(text); textareaRef.current?.focus(); }}
                />
              </div>
            </div>
          ) : (
          <div className="flex-1 flex flex-col items-center justify-center px-6 pb-16 pt-40 sm:pt-0">
            <div className="relative max-w-3xl w-full">
              {meta && <EmptyHero meta={meta} absolute />}
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
          )
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
                      onRegenerate={
                        isLast && msg.role === "assistant" && !hasError && !isStreaming && !chatLoading
                          ? onRegenerate : undefined
                      }
                      onOpenFile={openFileInCanvas}
                    />
                  );
                })}
              </div>
              <div className="pointer-events-none sticky bottom-0 z-10 h-6 -mt-6 bg-[linear-gradient(to_top,var(--color-background)_0%,var(--color-background)_20%,transparent_100%)]" />
            </div>
            <div className="shrink-0 px-6 pb-2 pt-1">
              <div className="max-w-3xl mx-auto">
                {ask && (
                  <AskCard
                    key={ask.questions.map((q) => q.question).join("|")}
                    questions={ask.questions}
                    onSubmit={(lines) => {
                      track("ask_answered", { method: "option", chat_id: chatId,
                                              questions: ask.questions.length,
                                              multi: ask.questions.some((q) => q.multi),
                                              count: lines.length });
                      handleSubmit(lines.join("\n"), "ask");
                    }}
                    onDismiss={() => {
                      track("ask_dismissed", { chat_id: chatId });
                      setAsk(null);
                    }}
                  />
                )}
                {!ask && survey && !hushed && !isStreaming && (
                  <SurveyStrip survey={survey} onDone={() => setSurvey(null)} />
                )}
                <AnimatePresence initial={false}>
                  {queued.map((m) => (
                    <QueuedChip
                      key={m.id}
                      text={m.text}
                      held={heldRef.current}
                      onEdit={() => editQueued(m.id)}
                      onDismiss={() => dropQueued(m.id)}
                    />
                  ))}
                </AnimatePresence>
                {followUpsOn && followUp && !isStreaming && !ask && (
                  <FollowUpChip
                    text={followUp}
                    onAccept={() => {
                      track("followup_accepted", { method: "click" });
                      handleSubmit(followUp, "follow_up");
                    }}
                    onDismiss={() => setFollowUp(null)}
                  />
                )}
                <InputBox {...inputProps} />
              </div>
            </div>
          </>
        ))}
      </LayoutGroup>

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
      {settingsOpen && account && (
        <SettingsDialog account={account} onClose={() => setSettingsOpen(false)} />
      )}
      </div>
      <div className={cn(
        "flex min-h-0 overflow-hidden rtl:flex-row-reverse",
        isDesktop && rightOpen && "my-1 mr-1 rounded-xl border border-border bg-background",
        isDesktop && rightExpanded && "min-w-0 flex-1",
      )}>
      {files && (
        <Canvas
          working={workingPaths}
          tabs={canvasTabs}
          active={canvasActive}
          docked={isDesktop}
          hidden={canvasHidden}
          expanded={rightExpanded}
          onToggleExpand={() => setRightExpanded((e) => !e)}
          onCloseAll={() => { setCanvasTabs([]); setCanvasActive(null); setRightExpanded(false); }}
          onSelectTab={setCanvasActive}
          onCloseTab={closeCanvasTab}
          onReorder={setCanvasTabs}
          onHide={() => setCanvasHidden(true)}
          onAddFile={openFileInCanvas}
          apps={apps}
          onAddApp={openApp}
          searchFiles={files.searchFiles}
          readFile={files.readFile}
          openFile={files.onOpenFile}
          writeFile={files.writeFile}
          listFolders={files.listFolders}
          org={files.org}
          onShareFile={files.onShareFile}
          railWidth={railPx}
          reloadKey={reloadKey}
        />
      )}
      {/* Chats / Files / Apps / Shares — docked on desktop, overlay on a phone */}
      <AnimatePresence initial={false}>
        {filesOpen && (
          <>
            {!isDesktop && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
              className="fixed inset-0 z-50 bg-black/30 backdrop-blur-[2px]"
              onClick={() => setFilesOpen(false)}
            />
            )}
            <motion.div
              initial={isDesktop ? { width: 0 } : { x: "100%" }}
              animate={!isDesktop ? { x: 0 }
                : rightExpanded && !canvasShowing ? {}
                : { width: railIconsOnly ? RAIL_ICON_W : panelWidth }}
              exit={!isDesktop ? { x: "100%" } : { width: 0 }}
              transition={railResizing ? { duration: 0 } : slide}
              className={cn(
                "flex flex-col overflow-hidden",
                isDesktop
                  ? cn("relative border-l border-border bg-background",
                       rightExpanded && !canvasShowing ? "min-w-0 flex-1" : "shrink-0")
                  : "fixed z-50 rounded-xl border border-border bg-background top-1 right-1 bottom-1 w-[calc(100%-0.5rem)] max-w-[calc(100%-0.5rem)]",
              )}
            >
              {/* Resize handle (left edge) — desktop only */}
              {isDesktop && (
                <div
                  onMouseDown={startResize}
                  className="absolute left-0 top-0 bottom-0 z-20 hidden sm:block w-1.5 -ml-0.5 cursor-ew-resize hover:bg-accent/30"
                  aria-label="Resize panel"
                />
              )}
              {/* Tab bar — icon strip once collapsed */}
              {railIconsOnly ? (
                <div className="flex flex-col items-center gap-1 border-b border-border py-2">
                  {([["chats", "list", !!account], ["files", "folder", !!files],
                     ["apps", "grid", !!files], ["shares", "link", !!account]] as const)
                    .filter(([, , on]) => on)
                    .map(([tab, icon]) => (
                      <button
                        key={tab}
                        onClick={() => { setRailIcons(false); selectTab(tab as typeof filesTab); }}
                        className={`flex size-8 items-center justify-center rounded-lg transition-colors cursor-pointer ${filesTab === tab ? "text-foreground bg-secondary/60" : "text-muted-foreground hover:text-foreground hover:bg-secondary/80"}`}
                        aria-label={t(tab)}
                        title={t(tab)}
                      >
                        <Icon name={icon} className="size-4" />
                      </button>
                    ))}
                </div>
              ) : (files || account) && (
                <div className="flex h-11 shrink-0 items-center border-b border-border px-2">
                  {account && (
                    <button
                      onClick={() => selectTab("chats")}
                      className={`h-full px-3 text-sm font-medium border-b-2 transition-colors cursor-pointer ${filesTab === "chats" ? "border-foreground text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`}
                    >
                      {t("chats")}
                    </button>
                  )}
                  {files && (
                    <button
                      onClick={() => selectTab("files")}
                      className={`h-full px-3 text-sm font-medium border-b-2 transition-colors cursor-pointer ${filesTab === "files" ? "border-foreground text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`}
                    >
                      {t("files")}
                    </button>
                  )}
                  {files && (
                    <button
                      onClick={() => { selectTab("apps"); void refreshApps(); }}
                      className={`h-full px-3 text-sm font-medium border-b-2 transition-colors cursor-pointer ${filesTab === "apps" ? "border-foreground text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`}
                    >
                      {t("apps")}
                    </button>
                  )}
                  {account && (
                    <button
                      onClick={() => selectTab("shares")}
                      className={`h-full px-3 text-sm font-medium border-b-2 transition-colors cursor-pointer ${filesTab === "shares" ? "border-foreground text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`}
                    >
                      {t("shares")}
                    </button>
                  )}
                  <div className="flex-1" />
                  <button
                    onClick={collapseRail}
                    className="flex size-8 items-center justify-center rounded-lg text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
                    aria-label={t("collapse")}
                    title={t("collapse")}
                  >
                    <Icon name="chevron-right" className="size-4" />
                  </button>
                </div>
              )}
              {!railIconsOnly && (filesTab === "files" && files ? (
                <>
                  <Files {...files} onDelete={deleteWithUndo} onOpenInCanvas={(path, name) => { openFileInCanvas(path, name); if (!isDesktop) setFilesOpen(false); }} maxUpload={config?.max_upload} />
                  <TrashLink label={t("trash")} count={trashRows.length} onClick={() => { setTrashFilter(undefined); selectTab("trash"); }} />
                </>
              ) : filesTab === "apps" ? (
                <AppsPanel
                  apps={apps}
                  loading={appsLoading}
                  onOpen={(a) => { openApp(a); if (!isDesktop) setFilesOpen(false); }}
                  onRename={files ? (a, name) => { void updateApp(a, { name }); } : undefined}
                  onSetIcon={files ? (a, icon) => { void updateApp(a, { icon }); } : undefined}
                  onUploadIcon={files ? (a, f) => { uploadAppIcon(a, f).catch(() => toastError(t("uploadFailed"))); } : undefined}
                  onDelete={canPurge && files ? (a) => { void deleteWithUndo(`apps/${a.slug}`).then(() => refreshApps()); } : undefined}
                />
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
                <>
                <ChatsPanel
                  chats={chats}
                  loading={chatsLoading}
                  activeId={chatId}
                  onLoad={(id) => { onLoadChat?.(id); if (window.innerWidth < 640) setFilesOpen(false); }}
                  onDelete={(id) => {
                    const name = chats.find((x) => x.id === id)?.title || t("untitled");
                    setChatsLoading(true);
                    onDeleteChat?.(id)
                      .then(() => { setChats((prev) => prev.filter((x) => x.id !== id)); trashed(`chat:${id}`, "chat", name); })
                      .finally(() => setChatsLoading(false));
                  }}
                  onRename={async (id, title) => {
                    await onRenameChat?.(id, title);
                    setChats((prev) => prev.map((x) => x.id === id ? { ...x, title } : x));
                  }}
                  onToggleFavorite={async (id, on) => {
                    await onSetFavorite?.(id, on);
                    setChats((prev) => prev.map((x) => x.id === id ? { ...x, favoritedAt: on ? new Date().toISOString() : "" } : x));
                  }}
                />
                {files && <TrashLink label={t("recentlyDeleted")} onClick={() => { setTrashFilter("chat"); selectTab("trash"); }} />}
                </>
              ) : filesTab === "trash" && files ? (
                <TrashView
                  rows={trashRows}
                  loading={trashLoading}
                  canPurge={canPurge}
                  filter={trashFilter}
                  onBack={() => selectTab(trashFilter === "chat" ? "chats" : "files")}
                  onRestore={(r) => {
                    const name = r.kind === "chat" ? r.path : r.path.split("/").pop() || r.path;
                    files.onRestoreTrash?.(r.id, r.kind, "trash_tab")
                      .then(() => { toastInfo(t("restored").replace("{name}", name)); afterRestore(r.kind); })
                      .catch(() => toastError(t("restoreFailed")));
                  }}
                  onPurge={(r) => { files.onPurgeTrash?.(r.id, r.kind).then(loadTrash).catch(() => {}); }}
                  onEmpty={() => { files.onEmptyTrash?.().then(loadTrash).catch(() => {}); }}
                />
              ) : null)}
            </motion.div>
          </>
        )}
      </AnimatePresence>
      </div>
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

// A message waiting on the current run. Dashed border marks it as not-yet-
// sent; clicking pulls it back into the composer (the same gesture that
// accepts a follow-up), which is also the only way to send one while an
// explicit Stop is holding the queue.
function QueuedChip({ text, held, onEdit, onDismiss }: {
  text: string;
  held: boolean;
  onEdit: () => void;
  onDismiss: () => void;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 4 }}
      transition={{ duration: 0.15 }}
      className="mb-2 flex justify-end px-1"
    >
      <div className="flex max-w-full items-center gap-0.5 rounded-2xl border border-dashed border-border bg-secondary/40 py-1.5 ps-3.5 pe-1.5">
        <button
          onClick={onEdit}
          title={held ? t("queuedHeld") : t("queuedHint")}
          className="min-w-0 text-start text-sm leading-snug break-words text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
          dir="auto"
        >
          {text}
        </button>
        <button
          onClick={onDismiss}
          className="shrink-0 rounded-full p-1 text-muted-foreground/60 hover:bg-secondary hover:text-foreground transition-colors cursor-pointer"
          aria-label={t("dismiss")}
        >
          <Icon name="x" className="size-3" />
        </button>
      </div>
    </motion.div>
  );
}

// The agent's `ask` tool — a question card above the composer. Options are
// shortcuts, never a gate: the composer stays live and typing any reply
// answers too.
//
// Several questions step one at a time rather than stacking. Stacked, a
// three-question card is a form the user has to scan before answering any of
// it, and it crowds the composer off small screens; one at a time keeps each
// question the only thing being asked.
//
// How a step commits depends on what it is. A single-select row IS the answer,
// so tapping it advances (and on the last step, sends) — a radio that never
// gets to show a checked state would be decoration. Multi-select and open
// questions can't know when you're done, so they get an explicit Next/Submit.
function FollowUpChip({ text, onAccept, onDismiss }: {
  text: string;
  onAccept: () => void;
  onDismiss: () => void;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.15 }}
      className="mb-2 flex justify-start px-1"
    >
      {/* Logical padding (ps/pe) so the text side keeps its inset in RTL;
          long suggestions wrap inside the composer's width. */}
      <div className="flex max-w-full items-center gap-0.5 rounded-2xl border border-border bg-background py-1.5 ps-3.5 pe-1.5 shadow-sm">
        <button
          onClick={onAccept}
          title={t("followUpHint")}
          className="min-w-0 text-start text-sm leading-snug break-words text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
          dir="auto"
        >
          {text}
        </button>
        <button
          onClick={onDismiss}
          className="shrink-0 rounded-full p-1 text-muted-foreground/60 hover:bg-secondary hover:text-foreground transition-colors cursor-pointer"
          aria-label="Dismiss"
        >
          <Icon name="x" className="size-3" />
        </button>
      </div>
    </motion.div>
  );
}

// Footer link into the trash — Finder/Drive style, from where the loss happened.
function TrashLink({ label, count, onClick }: { label: string; count?: number; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="flex shrink-0 items-center gap-2 border-t border-border px-4 py-2.5 text-xs text-muted-foreground hover:text-foreground hover:bg-secondary/40 transition-colors cursor-pointer"
    >
      <svg className="size-3.5" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M6 7h12M9 7V5a1 1 0 011-1h4a1 1 0 011 1v2m-8 0l.7 12a1 1 0 001 .95h6.6a1 1 0 001-.95L17 7" />
      </svg>
      <span>{label}{count ? ` · ${count}` : ""}</span>
    </button>
  );
}

// The empty screen's brand hero. `absolute` floats it above the centered
// input (the classic layout); in flow it stacks over input + gallery. Also
// rendered by the signed-out public shell (App.tsx), same face both sides.
export function EmptyHero({ meta, absolute }: {
  meta: { name: string; description?: string; logo?: string };
  absolute?: boolean;
}) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ delay: 0.4 }}
      className={cn(
        "flex flex-col items-center gap-4 text-center",
        absolute ? "absolute bottom-full left-0 right-0 mb-10" : "mb-10",
      )}
    >
      {meta.logo && (meta.logo.startsWith("<") ? (
        <div className="size-16 rounded-xl overflow-hidden border border-border" dangerouslySetInnerHTML={{ __html: meta.logo }} />
      ) : (
        <img src={meta.logo} alt="" className="size-16 rounded-xl object-cover border border-border" />
      ))}
      <h2 className="text-2xl font-semibold text-foreground">{meta.name}</h2>
      {meta.description && <p className="text-base text-muted-foreground max-w-lg">{meta.description}</p>}
    </motion.div>
  );
}

export function Suggestions({
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
