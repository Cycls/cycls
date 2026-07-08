import { useState, useCallback, useRef } from "react";
import { useApi, reasonOf } from "./use-api";
import { track } from "../lib/posthog";
import { useToast } from "../lib/toast";

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
  delta?: string;    // a step_arg chunk on the wire (not stored)
  status?: string;
  callout?: string;
  style?: string;
  title?: string;
  src?: string;
  alt?: string;
  caption?: string;
  chat_id?: string;
  action?: string;
}

export type UIAction = { action: string } & Record<string, unknown>;
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
  analytics?: boolean;
  suggestions?: boolean;
  affiliate?: string;
  max_upload?: number;   // per-file upload cap in MB
  explore_enabled?: boolean;
  explore?: { slug: string; title: string; title_ar?: string; description: string; description_ar?: string; icon_svg?: string; link: string }[] | null;
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
  const [isStreaming, setIsStreaming] = useState(false);
  const [chatId, setChatId] = useState<string | null>(null);
  const [chatLoading, setChatLoading] = useState(false);
  const chatIdRef = useRef<string | null>(null);
  const messagesRef = useRef<Message[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const lastRequestRef = useRef<{ text: string; attachments?: Attachment[]; origin?: string } | null>(null);
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
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(`${baseUrl}/files/${uploadPath}`, {
        method: "PUT",
        headers: h,
        body: form,
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

  const send = useCallback(
    async (text: string, attachments?: Attachment[], origin: string = "keyboard") => {
      if (isStreaming) return;

      const userMessage: Message = { role: "user", content: text, attachments };
      const assistantMessage: Message = {
        role: "assistant",
        content: "",
        parts: [],
      };

      setMessages((prev) => [...prev, userMessage, assistantMessage]);
      setIsStreaming(true);

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

      const doFetch = async () => {
        const controller = new AbortController();
        abortRef.current = controller;

        const headers: Record<string, string> = {
          "Content-Type": "application/json",
          ...(await authHeaders()),
        };

        // Server loads history from disk; only ship the new user message.
        const currentMsgs = messagesRef.current;
        const newUserMsg = currentMsgs[currentMsgs.length - 2]; // -1 is the empty assistant placeholder
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
          body: JSON.stringify({ messages: [requestMessage] }),
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
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
            if (data === "[DONE]") continue;

            try {
              const item: Part = JSON.parse(data);
              const type = item.type;

              // Capture chat_id from server, don't add as part
              if (type === "chat_id" && item.chat_id) {
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
                track("agent_ui_action", {
                  ...ev,
                  chat_id: chatIdRef.current,
                });
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
                  if (type === "step") {
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

        // Success — clear retry ref
        lastRequestRef.current = null;
      };

      try {
        await doFetch();
      } catch (err) {
        // Only retry a pre-stream failure; once bytes flowed the server has
        // the turn and resubmitting would double-run it.
        if ((err as Error).name !== "AbortError" && !receivedData) {
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
              setMessages((prev) => {
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
        setIsStreaming(false);
        abortRef.current = null;
        // Server is the sole writer of chat metadata. The harness stamps
        // updatedAt + first-turn title during the stream — no FE save needed.
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

  const stop = useCallback(() => {
    if (abortRef.current) {
      track("generation_stopped", { chat_id: chatIdRef.current });
    }
    abortRef.current?.abort();
  }, []);

  const clear = useCallback(() => {
    track("chat_cleared", { chat_id: chatIdRef.current });
    abortRef.current?.abort();
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
    abortRef.current?.abort();
    setChatLoading(true);
    try {
      const chat = await (await api(`/chats/${id}`)).json();
      const loaded: Message[] = chat.messages || [];

      setMessages(loaded);
      setChatId(id);
      chatIdRef.current = id;
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
  }, [api]);

  const deleteChat = useCallback(async (id: string) => {
    await api(`/chats/${id}`, { method: "DELETE" });
    track("chat_deleted", { chat_id: id });
    if (chatIdRef.current === id) {
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
    chatLoading,
    chatId,
    send,
    retry,
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
    setUIHandler,
  };
}

export type ChatApi = ReturnType<typeof useChat>;
