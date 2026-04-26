import { useState, useCallback, useRef } from "react";
import { useAuthHeaders } from "./use-auth-headers";
import { track } from "../lib/posthog";

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
  logo: string;
}

export interface AppConfig {
  name?: string;
  pass_metadata?: { en: PassMetadata; ar: PassMetadata };
  auth?: boolean;
  voice?: boolean;
  pk?: string;
  analytics?: boolean;
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
  const { setGetToken, authHeaders, getToken } = useAuthHeaders();

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
    [baseUrl, authHeaders],
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
        const requestMessage = { role: newUserMsg.role, content, parts: newUserMsg.parts };

        const url = chatIdRef.current
          ? `${baseUrl}/chat?chat=${encodeURIComponent(chatIdRef.current)}`
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
                u.searchParams.set("chat", item.chat_id);
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

              // Same type as current? Merge
              if (currentPart && currentPart.type === type) {
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
        if ((err as Error).name !== "AbortError") {
          // Auto-retry once after a brief delay
          try {
            // Reset assistant message for retry
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
              // Both attempts failed — show error with retry button
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

        // Auto-save chat with full messages snapshot
        if (chatIdRef.current) {
          const sid = chatIdRef.current;
          const currentMessages = messagesRef.current;
          const firstUserMsg = currentMessages.find((m) => m.role === "user");
          const title = (firstUserMsg?.content || "").slice(0, 100);
          const authH = { "Content-Type": "application/json", ...(await authHeaders()) };
          fetch(`${baseUrl}/chats/${sid}`, {
            method: "PUT",
            headers: authH,
            body: JSON.stringify({ title, messages: currentMessages }),
          }).then((r) => { if (!r.ok) console.error("Session save failed:", r.status); })
            .catch((e) => console.error("Session save error:", e));
        }
      }
    },
    [messages, isStreaming, baseUrl, authHeaders],
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
    // Drop ?chat= from URL on clear
    const u = new URL(window.location.href);
    u.searchParams.delete("chat");
    window.history.replaceState({}, "", u.toString());
  }, []);

  const share = useCallback(async (title: string = "", author?: { name: string; imageUrl?: string }) => {
    const headers = { "Content-Type": "application/json", ...(await authHeaders()) };
    const res = await fetch(`${baseUrl}/share`, {
      method: "POST",
      headers,
      body: JSON.stringify({ messages, title, author }),
    });
    if (!res.ok) {
      track("share_create_failed", { status: res.status });
      throw new Error(`Share failed: ${res.status}`);
    }
    const { path } = await res.json();
    const shareUrl = `${window.location.origin}/shared/${path}`;
    track("share_created", {
      share_path: path,
      share_url: shareUrl,
      title,
      message_count: messages.length,
      chat_id: chatIdRef.current,
    });
    return shareUrl;
  }, [messages, baseUrl, authHeaders]);

  const listShares = useCallback(async () => {
    const headers = await authHeaders();
    const res = await fetch(`${baseUrl}/share`, { headers });
    if (!res.ok) return [];
    return res.json();
  }, [baseUrl, authHeaders]);

  const deleteShare = useCallback(async (id: string) => {
    const headers = await authHeaders();
    const res = await fetch(`${baseUrl}/share/${id}`, { method: "DELETE", headers });
    if (!res.ok) throw new Error(`Delete failed: ${res.status}`);
    track("share_deleted", { share_id: id });
  }, [baseUrl, authHeaders]);

  const listChats = useCallback(async () => {
    const headers = await authHeaders();
    const res = await fetch(`${baseUrl}/chats`, { headers });
    if (!res.ok) return [];
    return res.json();
  }, [baseUrl, authHeaders]);

  const loadChat = useCallback(async (id: string) => {
    abortRef.current?.abort();
    setChatLoading(true);
    try {
      const headers = await authHeaders();
      const res = await fetch(`${baseUrl}/chats/${id}`, { headers });
      if (!res.ok) throw new Error(`Load failed: ${res.status}`);
      const chat = await res.json();
      const loaded: Message[] = chat.messages || [];

      setMessages(loaded);
      setChatId(id);
      chatIdRef.current = id;
      const u = new URL(window.location.href);
      u.searchParams.set("chat", id);
      window.history.replaceState({}, "", u.toString());

      track("chat_loaded", {
        chat_id: id,
        message_count: loaded.length,
      });

      // Rebuild attachment URLs with fresh token (after render)
      const token = await getToken();
      if (token) {
        let changed = false;
        for (const m of loaded) {
          for (const att of m.attachments || []) {
            if (att.path) {
              att.url = `${baseUrl}/files/${att.path}?token=${token}`;
              changed = true;
            }
          }
        }
        if (changed) setMessages([...loaded]);
      }
    } finally {
      setChatLoading(false);
    }
  }, [baseUrl, authHeaders, getToken]);

  const deleteChat = useCallback(async (id: string) => {
    const headers = await authHeaders();
    const res = await fetch(`${baseUrl}/chats/${id}`, { method: "DELETE", headers });
    if (!res.ok) throw new Error(`Delete failed: ${res.status}`);
    track("chat_deleted", { chat_id: id });
    // If we deleted the current chat, clear it
    if (chatIdRef.current === id) {
      abortRef.current?.abort();
      setMessages([]);
      setChatId(null);
      chatIdRef.current = null;
      const u = new URL(window.location.href);
      u.searchParams.delete("chat");
      window.history.replaceState({}, "", u.toString());
    }
  }, [baseUrl, authHeaders]);

  return {
    messages,
    isStreaming,
    chatLoading,
    chatId,
    send,
    retry,
    stop,
    clear,
    share,
    listShares,
    deleteShare,
    listChats,
    loadChat,
    deleteChat,
    setGetToken,
    uploadFile,
    authHeaders,
    setUIHandler,
  };
}
