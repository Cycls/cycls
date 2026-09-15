import { useState, useCallback, useEffect, useRef } from "react";
import { useApi, reasonOf } from "./use-api";
import { track } from "../lib/analytics";
import { webSearchEnabled, autoApprove } from "../lib/utils";
import { useToast } from "../lib/toast";

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
  connector?: string; // a connector's tool: the name whose logo heads the call block
  icon?: string;     // a custom tool's own image, from `.on(icon=…)`
  result?: string;   // a connector call's outcome, bounded — the block's Response
  delta?: string;    // a step_arg chunk on the wire (not stored)
  status?: string;
  callout?: string;
  style?: string;
  title?: string;
  src?: string;
  alt?: string;
  caption?: string;
  chat_id?: string;
  first?: boolean;   // chat_id event: the account's first chat in this workspace
  action?: string;
  sources?: Source[];
}

export type UIAction = { action: string } & Record<string, unknown>;
export type SendExtra = { approvals?: string[]; connectors?: string[] };
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
  max_upload?: number;   // per-file upload cap in MB
  explore_enabled?: boolean;
  explore?: { slug: string; title: string; title_ar?: string; description: string; description_ar?: string; icon_svg?: string; link: string }[] | null;
  examples_enabled?: boolean;   // curated example gallery on the empty screen (cards from GET /examples)
  workspaces?: string | null;   // multi-workspace mode: null off, else team-create policy ("member"|"admin")
}

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
  const isStreaming = attached || runStatus === "running";
  const [chatId, setChatId] = useState<string | null>(null);
  const [chatLoading, setChatLoading] = useState(false);
  const chatIdRef = useRef<string | null>(null);
  const messagesRef = useRef<Message[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const lastRequestRef = useRef<{ text: string; attachments?: Attachment[]; origin?: string } | null>(null);
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
  }) => {
    const tail = data.messages || [];
    if (data.reset) setMessages(tail);
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
  const pollRun = useCallback(async (id: string) => {
    if (pollingRef.current) return;
    pollingRef.current = true;
    const view = viewRef.current;
    try {
      for (;;) {
        if (viewRef.current !== view) return;
        const q = cursorRef.current == null ? "" : `?since=${cursorRef.current}`;
        const res = await api(`/chats/${encodeURIComponent(id)}${q}`);
        if (res.status === 204) return;
        const data = await res.json();
        if (viewRef.current !== view) return;
        applyTail(data);
        setRunStatus(data.run ?? null);
        if (data.run !== "running") return;
        await new Promise((r) => setTimeout(r, 2000));
      }
    } catch {
      // Leave it: the next trigger (visibility, online, a send) retries.
    } finally {
      pollingRef.current = false;
    }
  }, [api, applyTail]);

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

      const userMessage: Message = { role: "user", content: text, attachments };
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
      setMessages((prev) => [...prev, ...(silent ? [] : [userMessage]), assistantMessage]);
      setAttached(true);
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
      lastRequestRef.current = { text, attachments, origin };

      let receivedData = false;
      let sawDone = false;   // the server's end marker; its absence means the run may live on

      const doFetch = async () => {
        const controller = new AbortController();
        abortRef.current = controller;

        const headers: Record<string, string> = {
          "Content-Type": "application/json",
          ...(await authHeaders()),
        };

        // Server loads history from disk; only ship the new user message —
        // the one built above, NOT a re-read of messagesRef. The ref only
        // catches up when React runs the updater, so a send dispatched from a
        // deferred callback (retry, regenerate) could otherwise read past the
        // end of a rewound list and throw before ever reaching fetch.
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
        const response = await fetch(url, {
          method: "POST",
          headers,
          body: JSON.stringify({ messages: [requestMessage],
                                 ...(webSearchEnabled() ? {} : { disabled_tools: ["WebSearch"] }),
                                 ...(autoApprove() ? {} : { auto: false }),
                                 ...(extra?.approvals?.length ? { approvals: extra.approvals } : {}),
                                 ...(extra?.connectors?.length ? { connectors: extra.connectors } : {}) }),
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

              // Agent-driven UI action — dispatch to handler, don't add as part,
              // don't persist in chat history
              if (type === "ui" && item.action) {
                const ev = item as unknown as UIAction;
                uiHandlerRef.current?.(ev);
                continue;
              }

              // Tool-call argument stream — fold the partial JSON into the
              // step it belongs to (a live preview of what the model is writing).
              if (type === "step_arg" && item.id) {
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
                  currentPart = { ...item };
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
        if (!sawDone && chatIdRef.current && mine()) void pollRun(chatIdRef.current);
        const stopped = !!abortRef.current?.signal.aborted;
        setAttached(false);
        abortRef.current = null;
        // Server is the sole writer of chat metadata. The harness stamps
        // updatedAt + first-turn title during the stream — no FE save needed.

        // One event per turn carrying the shape of the work — capability
        // usage without per-tool-call volume (the server logs those).
        const last = messagesRef.current[messagesRef.current.length - 1];
        if (last?.role === "assistant") {
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
          });
        }
      }
    },
    // `messages` is read via messagesRef inside; keeping it out of deps
    // means `send`'s identity doesn't change on every streamed token
    // (and downstream `useEffect([send])` callers don't re-fire).
    [isStreaming, baseUrl, authHeaders],
  );

  const retry = useCallback(() => {
    if (isStreaming || !lastRequestRef.current) return;
    track("message_retried", { chat_id: chatIdRef.current });
    const { text, attachments, origin } = lastRequestRef.current;
    // Remove the last assistant message (the error one)
    setMessages((prev) => {
      const updated = [...prev];
      if (updated.length >= 2 && updated[updated.length - 1].role === "assistant") {
        // Remove both the failed assistant and the user message — send() will re-add them
        updated.splice(updated.length - 2, 2);
      }
      return updated;
    });
    // Re-send after state update
    setTimeout(() => send(text, attachments, origin), 0);
  }, [isStreaming, send]);

  // Re-run the last exchange. The server holds the finished turn on disk, so
  // the old one has to be dropped there BEFORE re-sending — otherwise the
  // resend appends a duplicate exchange instead of replacing it. A failed
  // truncate aborts the whole thing (api() has already toasted the reason)
  // rather than leaving history doubled.
  const regenerate = useCallback(async () => {
    if (isStreaming) return;
    const msgs = messagesRef.current;
    let i = msgs.length - 1;
    while (i >= 0 && msgs[i].role !== "user") i--;
    if (i < 0) return;
    const { content, attachments } = msgs[i];
    if (chatIdRef.current) {
      try {
        await api(`/chats/${encodeURIComponent(chatIdRef.current)}/last-exchange`, { method: "DELETE" });
      } catch { return; }
    }
    track("message_regenerated", { chat_id: chatIdRef.current, message_count: msgs.length });
    setMessages(msgs.slice(0, i));
    setTimeout(() => send(content, attachments, "regenerate"), 0);
  }, [isStreaming, send, api, setMessages]);

  const stop = useCallback(() => {
    if (abortRef.current) {
      track("generation_stopped", { chat_id: chatIdRef.current });
    }
    abortRef.current?.abort();
  }, []);

  const clear = useCallback(() => {
    track("chat_cleared", { chat_id: chatIdRef.current });
    viewRef.current += 1;
    abortRef.current?.abort();
    cursorRef.current = openRef.current = null;
    setRunStatus(null);
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
    abortRef.current?.abort();
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
            att.url = URL.createObjectURL(await (await api(`/files/${att.path}`)).blob());
          } catch (e) { console.warn(`attachment fetch failed: ${att.path}`, e); }
        }));
        setMessages([...loaded]);
      }
    } finally {
      setChatLoading(false);
    }
  }, [api, pollRun, setMessages]);

  const deleteChat = useCallback(async (id: string) => {
    await api(`/chats/${id}`, { method: "DELETE" });
    track("chat_deleted", { chat_id: id });
    if (chatIdRef.current === id) {
      viewRef.current += 1;
      abortRef.current?.abort();
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

  return {
    messages,
    isStreaming,
    runStatus,   // "running" while the server still has work, even with no stream
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
  };
}

export type ChatApi = ReturnType<typeof useChat>;
