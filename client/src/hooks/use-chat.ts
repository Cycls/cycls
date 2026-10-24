import { useState, useCallback, useEffect, useRef } from "react";
import { useApi, reasonOf } from "./use-api";
import { encPath } from "./use-files";
import type { DesignSelection } from "../components/design-editor-view";
import { track } from "../lib/analytics";
import { webSearchEnabled, autoApprove } from "../lib/utils";
import { useToast } from "../lib/toast";
import { fetchAuthed } from "./use-auth-headers";

// One search result, as the search engine returned it. A citation chip only
// ever renders from one of these, so a URL the model invented can't pose as a
// source — it stays an ordinary link.
export interface Source {
  title: string;
  url: string;
  snippet?: string;
}

export interface Part {
  type: string;
  text?: string;
  thinking?: string;
  code?: string;
  language?: string;
  headers?: string[];
  rows?: string[][];
  row?: string[];
  step?: string;
  tool_name?: string;
  ok?: boolean; // false when the tool call errored (refetch projection)
  id?: string;       // tool-call id — threads ToolStart → step_arg → final step
  args?: string;     // accumulated tool-call input (partial JSON), for the live preview
  at?: number;       // when this tab first saw the step (not stored), for its elapsed time
  connector?: string; // a connector's tool: the name whose logo heads the call block
  icon?: string;     // a custom tool's own image, from `.on(icon=…)`
  result?: string;   // a connector call's outcome, bounded — the block's Response
  delta?: string;    // a step_arg chunk on the wire (not stored)
  status?: string;
  callout?: string;
  style?: string;
  error_id?: string;   // a run that crashed: the reference it showed, and the key to the server's error log
  title?: string;
  src?: string;
  alt?: string;
  caption?: string;
  chat_id?: string;
  first?: boolean;   // chat_id event: the account's first chat in this workspace
  action?: string;
  sources?: Source[];
  card?: Record<string, unknown>;   // a confirm card, standing in the conversation where its step was
  state?: string;   // its answer: waiting · approved · done · failed · declined · skipped
  remembered?: boolean;   // answered with "Don't ask again"
}

export type UIAction = { action: string } & Record<string, unknown>;
export type SendExtra = {
  approvals?: string[]; declined?: string[]; connectors?: string[]; selection?: DesignSelection;
  folder?: string;   // the folder open in Files: where the agent saves a design named without one
  replay?: "regenerate" | "retry";   // the server runs the turn it saved again, not this copy of it
};
// What was sent: what retry sends again, and what Stop gives back to the composer.
export type Sent = { text: string; attachments?: Attachment[]; origin?: string; extra?: SendExtra };
export type UIHandler = (ev: UIAction) => void;

export interface Attachment {
  name: string;
  size: number;
  type: string;
  url: string;
  path?: string;
  status?: "uploading" | "error";
}

export interface Message {
  role: "user" | "assistant";
  content: string;
  parts?: Part[];
  attachments?: Attachment[];
  selection?: DesignSelection;   // a user message's attached design selection (shown as a chip)
}

export interface PassMetadata {
  name: string;
  description: string;
  logo: string;    // agent icon — chat hero
  brand?: string;  // brand wordmark — nav bar
}

export interface AppConfig {
  name?: string;
  pass_metadata?: { en: PassMetadata; ar: PassMetadata };
  auth?: boolean;
  voice?: boolean;
  pk?: string;
  one_tap?: boolean;
  analytics?: { provider: string; events?: string[]; [k: string]: unknown }[] | null;
  notifications?: { provider: string; [k: string]: unknown }[] | null;   // push plugins
  suggestions?: boolean;
  affiliate?: string;
  mobile_app?: { ios?: string; android?: string } | null;   // store links for the phone banner
  max_upload?: number;   // per-file upload cap in MB
  explore_enabled?: boolean;
  explore?: { slug: string; title: string; title_ar?: string; description: string; description_ar?: string; icon_svg?: string; link: string }[] | null;
  examples_enabled?: boolean;   // curated example gallery on the empty screen (cards from GET /examples)
  workspaces?: string | null;   // multi-workspace mode: null off, else team-create policy ("member"|"admin")
  design_editor_url?: string;   // base URL of the embedded design editor for .fig files (env DESIGN_EDITOR_URL)
}

// How a message is named to the server: by regenerate, retry, and a stopped prompt taken back.
async function sha256Hex(text: string): Promise<string | null> {
  try {
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
    return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
  } catch {
    return null;   // no WebCrypto (an insecure origin)
  }
}

// A confirm card's parts, changed where they stand.
const withCards = (msgs: Message[], change: (p: Part) => Part) =>
  msgs.map((m) => (m.parts?.some((p) => p.type === "card") ? { ...m, parts: m.parts.map((p) => (p.type === "card" ? change(p) : p)) } : m));
// A card still waiting when the person typed something else was skipped; the server reads it the same way.
const skipWaiting = (msgs: Message[]) => withCards(msgs, (p) => (p.state === "waiting" ? { ...p, state: "skipped" } : p));
// After an approval's run, its card reads how the call went: the step made again, by the same name and words.
const settle = (msgs: Message[], keys: string[], ran: Part[]) => withCards(msgs, (p) => {
  if (p.state !== "approved" || !keys.includes(String(p.card?.key))) return p;
  const step = ran.find((s) => s.type === "step" && s.tool_name === p.card?.tool_name && s.step === p.card?.step);
  return step ? { ...p, state: step.ok === false ? "failed" : "done" } : p;
});

export function useChat(baseUrl: string = "") {
  const [messages, _setMessages] = useState<Message[]>([]);
  const setMessages = useCallback((updater: Message[] | ((prev: Message[]) => Message[])) => {
    _setMessages((prev) => {
      const next = typeof updater === "function" ? updater(prev) : updater;
      messagesRef.current = next;
      return next;
    });
  }, []);
  // Two facts, not one. `attached` is "a stream is feeding this tab"; `runStatus`
  // is "the server says the run is alive". They diverge the moment a run outlives
  // its connection, which is the whole point of the design.
  const [attached, setAttached] = useState(false);
  const [runStatus, setRunStatus] = useState<string | null>(null);
  const [runStartedAt, setRunStartedAt] = useState<string | null>(null);
  const isStreaming = attached || runStatus === "running";
  const [chatId, setChatId] = useState<string | null>(null);
  const [chatLoading, setChatLoading] = useState(false);
  const chatIdRef = useRef<string | null>(null);
  const messagesRef = useRef<Message[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const lastRequestRef = useRef<Sent | null>(null);
  // Which conversation the view is showing. A run captures it when it starts and
  // writes nothing once it no longer matches — the chat id is not enough, since a
  // run can learn its id after the user has already moved on.
  const viewRef = useRef(0);
  const cursorRef = useRef<number | null>(null);   // server-reported turn index, never messages.length
  const openRef = useRef<string | null>(null);     // role of the last rendered message
  const pollingRef = useRef(false);
  const uiHandlerRef = useRef<UIHandler | null>(null);
  const setUIHandler = useCallback((h: UIHandler | null) => {
    uiHandlerRef.current = h;
  }, []);
  // Where Stop gives a prompt back: the composer, registered by the chat that owns it.
  const restoreRef = useRef<((sent: Sent) => void) | null>(null);
  const setRestoreHandler = useCallback((h: ((sent: Sent) => void) | null) => {
    restoreRef.current = h;
  }, []);
  const { api, authHeaders, setGetToken } = useApi(baseUrl);
  const { error: toastError } = useToast();

  const uploadFile = useCallback(
    async (file: File): Promise<Attachment> => {
      const h = await authHeaders();
      const id = crypto.randomUUID().slice(0, 8);
      const uploadPath = `attachments/${id}-${file.name}`;
      // Raw body, not multipart — auth runs before the body is read, so slow uploads can't outlive the JWT.
      const res = await fetch(`${baseUrl}/files/${uploadPath}`, {
        method: "PUT",
        headers: h,
        body: file,
      });
      if (!res.ok) {
        track("file_upload_failed", {
          file_name: file.name,
          file_type: file.type,
          file_size: file.size,
          status: res.status,
        });
        toastError(await reasonOf(res));
        throw new Error(`Upload failed: ${res.status}`);
      }
      track("file_uploaded", {
        file_name: file.name,
        file_type: file.type,
        file_size: file.size,
        context: "chat_attachment",
      });
      return { name: file.name, size: file.size, type: file.type, url: "", path: uploadPath };
    },
    [baseUrl, authHeaders, toastError],
  );

  // Fold a window of new turns onto what is on screen. The server merges
  // consecutive assistant turns into one bubble, so the first message of a window
  // may be a continuation of the last one rendered — `open` is how we know.
  const applyTail = useCallback((data: {
    messages?: Message[]; next?: number; open?: string | null; reset?: boolean;
  }, replace = false) => {
    const tail = data.messages || [];
    if (data.reset || (replace && tail.length)) setMessages(tail);
    else if (tail.length) setMessages((prev) => {
      const out = [...prev];
      const last = out[out.length - 1];
      let i = 0;
      if (openRef.current === "assistant" && tail[0].role === "assistant" && last?.role === "assistant") {
        out[out.length - 1] = { ...last, content: last.content + tail[0].content,
                                parts: [...(last.parts || []), ...(tail[0].parts || [])] };
        i = 1;
      }
      return [...out, ...tail.slice(i)];
    });
    if (typeof data.next === "number") cursorRef.current = data.next;
    if (tail.length && data.open !== undefined) openRef.current = data.open;
  }, [setMessages]);

  // Watch a run we are not streaming. The run outlives its request, so a stream
  // that ended is not a turn that ended — only the record says that.
  // `dropped`: this tab's stream for the run ended early, so its ending is this tab's to report.
  const pollRun = useCallback(async (id: string, dropped = false) => {
    if (pollingRef.current) return;
    pollingRef.current = true;
    const view = viewRef.current;
    // An ending is reported once: a run this poll saw running, or one whose stream just dropped —
    // never the last run's status, which every refocus of a finished chat reads again.
    let ours = dropped;
    try {
      for (;;) {
        if (viewRef.current !== view) return;
        const full = cursorRef.current == null;
        const q = full ? "" : `?since=${cursorRef.current}`;
        const res = await api(`/chats/${encodeURIComponent(id)}${q}`);
        if (res.status === 204) return;
        const data = await res.json();
        if (viewRef.current !== view) return;
        applyTail(data, full);
        setRunStatus(data.run ?? null);
        setRunStartedAt(data.run_started ?? null);
        if (data.run !== "running") {
          if (data.run && ours) {
            track("turn_completed", { chat_id: id, status: data.run, detached: true });
            if (data.run === "failed" || data.run === "interrupted")
              track("run_failed", { chat_id: id, status: data.run, reason: data.run_reason, error_id: data.run_error, via: "poll" });
          }
          return;
        }
        ours = true;
        await new Promise((r) => setTimeout(r, 2000));
      }
    } catch {
      // Leave it: the next trigger (visibility, online, a send) retries.
    } finally {
      pollingRef.current = false;
    }
  }, [api, applyTail]);

  // Edge does not sleep a tab holding a Web Lock and Chrome does not freeze one,
  // and a locked screen is where most mobile-web drops come from. This is the only
  // part of the design that reduces how often a connection drops at all.
  useEffect(() => {
    if (!isStreaming) return;
    let done = false;
    const release: (() => void)[] = [];
    const locks = navigator as Navigator & {
      locks?: { request: (n: string, f: () => Promise<void>) => Promise<void> };
      wakeLock?: { request: (t: "screen") => Promise<{ release: () => Promise<void> }> };
    };
    locks.locks?.request("cycls-run", () => new Promise<void>((r) => {
      if (done) r(); else release.push(r);
    })).catch(() => {});
    locks.wakeLock?.request("screen")
      .then((w) => { if (done) void w.release(); else release.push(() => void w.release()); })
      .catch(() => {});
    return () => { done = true; release.forEach((f) => f()); };
  }, [isStreaming]);

  // Coming back is the common case the whole design exists for: the tab was
  // parked or the phone was locked, and the run kept going without us.
  useEffect(() => {
    const check = () => {
      if (document.visibilityState !== "visible") return;
      if (chatIdRef.current && !attached) void pollRun(chatIdRef.current);
    };
    document.addEventListener("visibilitychange", check);
    window.addEventListener("online", check);
    return () => {
      document.removeEventListener("visibilitychange", check);
      window.removeEventListener("online", check);
    };
  }, [attached, pollRun]);

  const send = useCallback(
    async (text: string, attachments?: Attachment[], origin: string = "keyboard", extra?: SendExtra) => {
      if (isStreaming) return;

      const userMessage: Message = { role: "user", content: text, attachments, ...(extra?.selection ? { selection: extra.selection } : {}) };
      const assistantMessage: Message = {
        role: "assistant",
        content: "",
        parts: [],
      };

      // An approval carried back from a confirm card is machinery, not something the person typed —
      // it goes to the model and the server stores it `internal`, so the chat shows no bubble for it.
      const silent = origin === "confirm";
      const view = viewRef.current;
      const mine = () => viewRef.current === view;
      setMessages((prev) => [...(silent ? prev : skipWaiting(prev)), ...(silent ? [] : [userMessage]), assistantMessage]);
      setAttached(true);
      setRunStartedAt((prev) => prev ?? new Date().toISOString());
      const sentAt = Date.now();

      track("message_sent", {
        message_length: text.length,
        has_attachments: !!(attachments && attachments.length),
        attachment_count: attachments?.length || 0,
        is_new_chat: !chatIdRef.current,
        chat_id: chatIdRef.current,
        origin,
      });

      // Store for retry
      lastRequestRef.current = { text, attachments, origin, extra };

      let receivedData = false;
      let sawDone = false;   // the server's end marker; its absence means the run may live on
      let crashed: string | undefined;   // the run failed while this tab watched: the reference it was shown

      const doFetch = async () => {
        const controller = new AbortController();
        abortRef.current = controller;

        const headers: Record<string, string> = { "Content-Type": "application/json" };

        // Server loads history from disk; only ship the new user message —
        // the one built above, NOT a re-read of messagesRef. The ref only
        // catches up when React runs the updater, so a send right after a
        // rewind (retry, regenerate) could otherwise read past the end of the
        // rewound list and throw before ever reaching fetch.
        const newUserMsg = userMessage;
        const withPaths = newUserMsg.attachments?.filter((a) => a.path);
        let content: string | Record<string, string>[] = newUserMsg.content;
        if (withPaths && withPaths.length > 0) {
          const parts: Record<string, string>[] = [{ type: "text", text: newUserMsg.content }];
          for (const att of withPaths) {
            if (att.type.startsWith("image/")) {
              parts.push({ type: "image", image: att.path! });
            } else {
              parts.push({ type: "file", file: att.path! });
            }
          }
          content = parts;
        }
        const requestMessage = { role: newUserMsg.role, content, parts: newUserMsg.parts,
                                 attachments: newUserMsg.attachments };

        const url = chatIdRef.current
          ? `${baseUrl}/chat?id=${encodeURIComponent(chatIdRef.current)}`
          : `${baseUrl}/chat`;
        // A replay names the saved turn by a hash of what was typed; "" (no WebCrypto) names none.
        const replay = extra?.replay ? { [extra.replay]: (await sha256Hex(text)) ?? "" } : {};
        const response = await fetchAuthed(url, {
          method: "POST",
          headers,
          body: JSON.stringify({ messages: [requestMessage],
                                 ...(webSearchEnabled() ? {} : { disabled_tools: ["WebSearch"] }),
                                 detach: true,   // we poll, and we stop through the endpoint
                                 ...(autoApprove() ? {} : { auto: false }),
                                 ...(extra?.approvals?.length ? { approvals: extra.approvals } : {}),
                                 ...(extra?.declined?.length ? { declined: extra.declined } : {}),
                                 ...(extra?.connectors?.length ? { connectors: extra.connectors } : {}),
                                 ...(extra?.selection ? { selection: extra.selection } : {}),
                                 ...(extra?.folder ? { folder: extra.folder } : {}),
                                 ...replay }),
          signal: controller.signal,
        });

        if (!response.ok) {
          const err = new Error(
            response.status === 409 ? await reasonOf(response) : `HTTP ${response.status}`,
          ) as Error & { status?: number };
          err.status = response.status;
          throw err;
        }

        const reader = response.body!.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let currentPart: Part | null = null;
        const parts: Part[] = [];

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          receivedData = true;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            const data = line.slice(6);
            if (data === "[DONE]") { sawDone = true; continue; }

            try {
              const item: Part = JSON.parse(data);
              const type = item.type;
              if (type === "callout" && item.error_id) crashed = item.error_id;

              // Capture chat_id from server, don't add as part
              if (type === "chat_id" && item.chat_id) {
                // The server knows whether this account had any chat before —
                // a browser flag can't (existing users on a new device).
                if (item.first) track("first_agent_use", {});
                if (!mine()) continue;   // the view moved on before the id arrived
                chatIdRef.current = item.chat_id;
                setChatId(item.chat_id);
                // Reflect in browser URL so the chat is bookmarkable/shareable
                const u = new URL(window.location.href);
                u.searchParams.set("id", item.chat_id);
                window.history.replaceState({}, "", u.toString());
                continue;
              }

              // Agent-driven UI action — dispatch to handler, don't add as part. A confirm card is the
              // one that stays: it stands in the conversation, in the place of the step it holds back.
              if (type === "ui" && item.action) {
                const ev = item as unknown as UIAction;
                uiHandlerRef.current?.(ev);
                if (ev.action !== "confirm") continue;
                const held = parts.findIndex((p) => p.type === "step" && p.id === ev.id);
                if (held >= 0) parts.splice(held, 1);
                currentPart = { type: "card", card: ev, state: "waiting" };
                parts.push(currentPart);
              // Tool-call argument stream — fold the partial JSON into the
              // step it belongs to (a live preview of what the model is writing).
              } else if (type === "step_arg" && item.id) {
                const t = parts.find((p) => p.type === "step" && p.id === item.id);
                if (t) t.args = (t.args || "") + (item.delta || "");
              } else if (type === "step" && item.id) {
                // Tool-call step — thread by id so ToolStart, its arg chunks,
                // and the final detail all land on one line, not three.
                const existing = parts.find((p) => p.type === "step" && p.id === item.id);
                if (existing) {
                  Object.assign(existing, item);
                  currentPart = existing;
                } else {
                  currentPart = { ...item, at: Date.now() };
                  parts.push(currentPart);
                }
              } else if (currentPart && currentPart.type === type) {
                // Same type as current? Merge
                if (item.row && currentPart.rows) {
                  currentPart.rows.push(item.row);
                } else if (
                  type in item &&
                  item[type as keyof Part] !== undefined
                ) {
                  const key = type as keyof Part;
                  // A non-string payload is a whole value, not a delta — two
                  // parallel searches each yield a complete `sources` array, and
                  // concatenating them would stringify both into garbage.
                  if (type === "step" || typeof item[key] !== "string") {
                    currentPart = { ...item };
                    parts.push(currentPart);
                  } else {
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    (currentPart as any)[key] =
                      ((currentPart[key] as string) || "") +
                      (item[key] as string);
                  }
                }
              } else {
                // New part
                currentPart = { ...item };
                if (item.headers) currentPart.rows = [];
                parts.push(currentPart);
              }

              // Update state
              if (!mine()) continue;
              setMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last?.role === "assistant") {
                  updated[updated.length - 1] = {
                    ...last,
                    parts: [...parts],
                  };
                }
                return updated;
              });
            } catch {
              // skip parse errors
            }
          }
        }

        // Clean up: filter empty text parts, set content
        const finalParts = parts.filter(
          (p) => p.type !== "text" || p.text?.trim(),
        );
        const contentText = finalParts
          .filter((p) => p.type === "text")
          .map((p) => p.text)
          .join("");

        if (mine()) {
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last?.role === "assistant") {
              updated[updated.length - 1] = {
                ...last,
                content: contentText,
                parts: finalParts,
              };
            }
            return updated;
          });
        }
        if (mine() && extra?.approvals?.length) setMessages((prev) => settle(prev, extra.approvals!, finalParts));

        // Success — clear retry ref
        lastRequestRef.current = null;
      };

      try {
        await doFetch();
      } catch (err) {
        // 409: the chat already has a run. Never retry — if it finishes in the
        // meantime the retry succeeds and sends the message twice.
        if ((err as Error & { status?: number }).status === 409) {
          track("run_busy", { chat_id: chatIdRef.current });
          if (chatIdRef.current) void pollRun(chatIdRef.current);
          if (mine()) setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last?.role === "assistant") {
              updated[updated.length - 1] = { ...last, parts: [
                { type: "callout", callout: (err as Error).message, style: "warning" }] };
            }
            return updated;
          });
        // Only retry a pre-stream failure; once bytes flowed the server has
        // the turn and resubmitting would double-run it.
        } else if ((err as Error).name !== "AbortError" && !receivedData && mine()) {
          try {
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last?.role === "assistant") {
                updated[updated.length - 1] = { ...last, content: "", parts: [] };
              }
              return updated;
            });
            await new Promise((r) => setTimeout(r, 1000));
            await doFetch();
          } catch (retryErr) {
            if ((retryErr as Error).name !== "AbortError") {
              track("message_failed", {
                error_message: (retryErr as Error).message,
                chat_id: chatIdRef.current,
              });
              if (mine()) setMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last?.role === "assistant") {
                  updated[updated.length - 1] = {
                    ...last,
                    parts: [
                      {
                        type: "callout",
                        callout: `Connection error: ${(retryErr as Error).message}`,
                        style: "error",
                      },
                    ],
                  };
                }
                return updated;
              });
            }
          }
        }
      } finally {
        // No end marker means the stream stopped before the run did — the record
        // is the only thing that knows which. Also covers a clean-looking read
        // that simply ran out, which is what a parked tab produces.
        cursorRef.current = null;   // nothing advanced it while streaming
        if (!sawDone && chatIdRef.current && mine()) void pollRun(chatIdRef.current, receivedData);
        const stopped = !!abortRef.current?.signal.aborted;
        setAttached(false);
        abortRef.current = null;
        // Server is the sole writer of chat metadata. The harness stamps
        // updatedAt + first-turn title during the stream — no FE save needed.

        // One event per turn carrying the shape of the work — capability
        // usage without per-tool-call volume (the server logs those). Only when
        // the stream carried the turn to its end: otherwise it would measure how
        // long this tab stayed attached, and the poll reports the real ending.
        const last = messagesRef.current[messagesRef.current.length - 1];
        if (sawDone && last?.role === "assistant") {
          const tools: Record<string, number> = {};
          let calls = 0;
          for (const p of last.parts || []) {
            if (p.type === "step" && p.tool_name) { tools[p.tool_name] = (tools[p.tool_name] || 0) + 1; calls++; }
          }
          track("turn_completed", {
            chat_id: chatIdRef.current,
            duration_s: Math.round((Date.now() - sentAt) / 1000),
            tool_calls: calls,
            tools,
            produced_artifact: (last.parts || []).some((p) => p.type === "step" && p.tool_name === "Canvas" && p.ok !== false),
            errored: (last.parts || []).some((p) => p.type === "callout" && p.style === "error"),
            stopped,
            origin,
            detached: false,
          });
        }
        if (sawDone && crashed)
          track("run_failed", { chat_id: chatIdRef.current, status: "failed", reason: "error", error_id: crashed, via: "stream" });
      }
    },
    // `messages` is read via messagesRef inside; keeping it out of deps
    // means `send`'s identity doesn't change on every streamed token
    // (and downstream `useEffect([send])` callers don't re-fire).
    [isStreaming, baseUrl, authHeaders],
  );

  // What was last sent: the request itself while this tab holds it, else the last message on
  // screen (a server-side failure ends the stream cleanly and clears the stored request).
  const lastSent = useCallback((): Sent | null => {
    if (lastRequestRef.current) return lastRequestRef.current;
    const msgs = messagesRef.current;
    let i = msgs.length - 1;
    while (i >= 0 && msgs[i].role !== "user") i--;
    if (i < 0) return null;
    const { content: text, attachments, selection } = msgs[i];
    return { text, attachments, origin: "retry", ...(selection ? { extra: { selection } } : {}) };
  }, []);

  // Send the failed turn again. If the server saved it and its run did not finish, it runs that
  // turn again in place (`retry`); otherwise the request never arrived, and this is it. A failed
  // regenerate is retried as one. An approval is not a turn a replay names: it goes again as it was.
  const retry = useCallback(() => {
    if (isStreaming) return;
    const request = lastSent();
    if (!request) return;
    const { text, attachments, origin, extra } = request;
    track("message_retried", { chat_id: chatIdRef.current });
    // send() puts the message back; a silent send (an approval) has no bubble, so only the reply goes.
    const msgs = messagesRef.current;
    let i = msgs.length - 1;
    while (i >= 0 && msgs[i].role !== "user") i--;
    const shown = i >= 0 && msgs[i].content === text && origin !== "confirm";
    setMessages(shown ? msgs.slice(0, i) : msgs[msgs.length - 1]?.role === "assistant" ? msgs.slice(0, -1) : msgs);
    return send(text, attachments, origin, { ...extra, replay: origin === "confirm" ? undefined : extra?.replay ?? "retry" });
  }, [isStreaming, send, setMessages, lastSent]);

  // Run the last exchange again: one request, and the server runs the turn it saved again rather
  // than a copy rebuilt from the screen, replacing only the reply after it. A second click, or
  // another tab, meets the chat's run lock like a second send.
  const regenerate = useCallback(() => {
    if (isStreaming) return;
    const msgs = messagesRef.current;
    let i = msgs.length - 1;
    while (i >= 0 && msgs[i].role !== "user") i--;
    if (i < 0) return;
    const { content, attachments, selection } = msgs[i];
    track("message_regenerated", { chat_id: chatIdRef.current, message_count: msgs.length });
    setMessages(msgs.slice(0, i));
    return send(content, attachments, "regenerate", { replay: "regenerate", ...(selection ? { selection } : {}) });
  }, [isStreaming, send, setMessages]);

  const stop = useCallback(async () => {
    const id = chatIdRef.current;
    track("generation_stopped", { chat_id: id });
    // Nothing of the reply shown yet (thinking aside, which is never kept): the prompt goes
    // straight back to the composer, and the run drops it as it ends if it kept nothing either.
    const msgs = messagesRef.current;
    const last = msgs[msgs.length - 1];
    const sent = lastSent();
    const shown = (last?.parts || []).some((p) => (p.type === "text" && p.text?.trim()) || (p.type === "step" && p.tool_name));
    const back = id && sent && sent.origin !== "confirm" && last?.role === "assistant" && !shown && restoreRef.current
      ? sent : null;
    if (back) {
      viewRef.current += 1;   // the stopped run writes nothing more here
      abortRef.current?.abort();
      cursorRef.current = openRef.current = null;
      setRunStatus("stopped");
      setMessages((prev) => {
        let j = prev.length - 1;
        while (j >= 0 && prev[j].role !== "user") j--;
        return j >= 0 && prev[j].content === back.text ? prev.slice(0, j) : prev;
      });
      restoreRef.current?.(back);
    }
    // Dropping the connection is no longer a stop — the run would keep going.
    // The endpoint is the only thing that cancels; it reaches a run on another
    // container too, through the record.
    let taken = false;
    if (id) {
      try {
        const expect = back && await sha256Hex(back.text);
        const res = await api(`/chats/${encodeURIComponent(id)}/stop`,
                              { method: "POST", ...(expect ? { json: { take_back: expect } } : {}) });
        taken = !!(await res.json()).taken_back;
      } catch { /* it may already have finished; the poll below settles it */ }
    }
    if (back) {
      track("prompt_restored", { chat_id: id, taken_back: taken });
      if (!taken) void pollRun(id!);   // it kept a reply, or never had the prompt: show the chat as it is
      return;
    }
    const streaming = !!abortRef.current;
    abortRef.current?.abort();   // let go of the reader, for immediate feedback
    if (id && !streaming) void pollRun(id);   // a stream settles itself above
  }, [api, pollRun, lastSent, setMessages]);

  const clear = useCallback(() => {
    track("chat_cleared", { chat_id: chatIdRef.current });
    viewRef.current += 1;
    cursorRef.current = openRef.current = null;
    setRunStatus(null);
    setRunStartedAt(null);
    setMessages([]);
    setChatId(null);
    chatIdRef.current = null;
    // Drop ?id= from URL on clear
    const u = new URL(window.location.href);
    u.searchParams.delete("id");
    window.history.replaceState({}, "", u.toString());
  }, []);

  // Replace the conversation with a single system message — used to show fork
  // progress / errors on a fresh page load (the chat is empty at that point).
  const notify = useCallback((part: Part) => {
    setMessages([{ role: "assistant", content: "", parts: [part] }]);
  }, []);

  const share = useCallback(async (audience: string = "public", authorFields: {
    author_name?: string;
    author_image_url?: string;
    author_org_name?: string;
    author_org_image_url?: string;
  } = {}) => {
    const chatId = chatIdRef.current;
    if (!chatId) throw new Error("No chat to share");
    let res: Response;
    try {
      res = await api("/share", { method: "POST", json: { path: `chat/${chatId}`, audience, ...authorFields } });
    } catch (err) {
      track("share_create_failed", { status: (err as Error & { status?: number }).status });
      throw err;
    }
    const { url } = await res.json();
    const shareUrl = `${window.location.origin}${url}`;
    track("share_created", {
      chat_id: chatId,
      share_url: shareUrl,
      message_count: messagesRef.current.length,
    });
    return shareUrl;
  }, [api]);

  const listShares = useCallback(async () => {
    try { return await (await api("/share")).json(); } catch { return []; }
  }, [api]);

  const deleteShare = useCallback(async (token: string) => {
    await api(`/share/${token}`, { method: "DELETE" });
    track("share_deleted", { token });
  }, [api]);

  const forkShare = useCallback(async (userToken: string) => {
    // `<user>/<token>` with an optional `?ws=` — reattach it after /fork
    const [path, query] = userToken.split("?");
    const { id } = await (await api(`/share/${path}/fork${query ? `?${query}` : ""}`, { method: "POST" })).json();
    track("share_forked", { source: userToken, new_chat_id: id });
    return id as string;
  }, [api]);

  const listChats = useCallback(async () => {
    try { return await (await api("/chats")).json(); } catch { return []; }
  }, [api]);

  const loadChat = useCallback(async (id: string) => {
    viewRef.current += 1;   // whatever is streaming stops writing here
    setChatLoading(true);
    try {
      const chat = await (await api(`/chats/${id}`)).json();
      const loaded: Message[] = chat.messages || [];

      setMessages(loaded);
      setChatId(id);
      chatIdRef.current = id;
      // Seed the poll's cursor from the server, never from the array length:
      // the projection merges assistant turns and hides tool batches.
      cursorRef.current = typeof chat.next === "number" ? chat.next : null;
      openRef.current = chat.open ?? (loaded.length ? loaded[loaded.length - 1].role : null);
      setRunStatus(chat.run ?? null);
      setRunStartedAt(chat.run_started ?? null);
      if (chat.run === "running") void pollRun(id);   // opened a chat that is still working
      const u = new URL(window.location.href);
      u.searchParams.set("id", id);
      window.history.replaceState({}, "", u.toString());

      track("chat_loaded", { chat_id: id, message_count: loaded.length });

      // Auth on /files/{path} is header-only by design (no ?token= URL
      // fallback — JWTs in URLs leak through history/logs/Referer). So
      // <img src> can't load directly. Fetch each attachment with the
      // bearer header and turn it into a blob URL the browser can render.
      const refs = loaded.flatMap((m) => (m.attachments || []).filter((a) => a.path));
      if (refs.length) {
        await Promise.all(refs.map(async (att) => {
          try {
            att.url = URL.createObjectURL(await (await api(`/files/${encPath(att.path ?? "")}`)).blob());
          } catch (e) { console.warn(`attachment fetch failed: ${att.path}`, e); }
        }));
        setMessages([...loaded]);
      }
    } finally {
      setChatLoading(false);
    }
  }, [api, pollRun, setMessages]);

  const deleteChat = useCallback(async (id: string) => {
    // Stop first: a detached run would otherwise keep working, and keep
    // heartbeating, into a chat the person just deleted.
    try { await api(`/chats/${encodeURIComponent(id)}/stop`, { method: "POST" }); } catch { /* none running */ }
    await api(`/chats/${id}`, { method: "DELETE" });
    track("chat_deleted", { chat_id: id });
    if (chatIdRef.current === id) {
      viewRef.current += 1;
      abortRef.current?.abort();
      cursorRef.current = openRef.current = null;
      setRunStatus(null);
      setRunStartedAt(null);
      setMessages([]);
      setChatId(null);
      chatIdRef.current = null;
      const u = new URL(window.location.href);
      u.searchParams.delete("id");
      window.history.replaceState({}, "", u.toString());
    }
  }, [api]);

  const renameChat = useCallback(async (id: string, title: string) => {
    await api(`/chats/${id}`, { method: "PUT", json: { title } });
    track("chat_renamed", { chat_id: id });
  }, [api]);

  const setFavorite = useCallback(async (id: string, on: boolean) => {
    const favoritedAt = on ? new Date().toISOString() : null;
    await api(`/chats/${id}`, { method: "PUT", json: { favoritedAt } });
    track("chat_favorited", { chat_id: id, on });
  }, [api]);

  // A confirm card's answer, shown at once; the turn that carries it saves it.
  const markCard = useCallback((key: string, patch: Partial<Part>) =>
    setMessages((prev) => withCards(prev, (p) => (p.card?.key === key ? { ...p, ...patch } : p))), []);

  return {
    messages,
    markCard,
    isStreaming,
    attached,    // a stream is feeding this tab right now
    runStatus,   // "running" while the server still has work, even with no stream
    runStartedAt,
    chatLoading,
    chatId,
    send,
    retry,
    regenerate,
    stop,
    clear,
    notify,
    share,
    listShares,
    deleteShare,
    forkShare,
    listChats,
    loadChat,
    deleteChat,
    renameChat,
    setFavorite,
    setGetToken,
    uploadFile,
    authHeaders,
    api,
    setUIHandler,
    setRestoreHandler,
  };
}

export type ChatApi = ReturnType<typeof useChat>;
