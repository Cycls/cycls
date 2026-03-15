import { useState, useCallback, useRef } from "react";
import { useAuthHeaders } from "./use-auth-headers";

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
  session_id?: string;
}

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

export interface AppConfig {
  name?: string;
  auth?: boolean;
  pk?: string;
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
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionLoading, setSessionLoading] = useState(false);
  const sessionIdRef = useRef<string | null>(null);
  const messagesRef = useRef<Message[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const lastRequestRef = useRef<{ text: string; attachments?: Attachment[] } | null>(null);
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
      if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
      return { name: file.name, size: file.size, type: file.type, url: "", path: uploadPath };
    },
    [baseUrl, authHeaders],
  );

  const send = useCallback(
    async (text: string, attachments?: Attachment[]) => {
      if (isStreaming) return;

      const userMessage: Message = { role: "user", content: text, attachments };
      const assistantMessage: Message = {
        role: "assistant",
        content: "",
        parts: [],
      };

      setMessages((prev) => [...prev, userMessage, assistantMessage]);
      setIsStreaming(true);

      // Store for retry
      lastRequestRef.current = { text, attachments };

      const doFetch = async () => {
        const controller = new AbortController();
        abortRef.current = controller;

        const headers: Record<string, string> = {
          "Content-Type": "application/json",
          ...(await authHeaders()),
        };

        // Build request messages (all except the empty assistant we just added)
        const currentMsgs = messagesRef.current;
        const requestMessages = currentMsgs.slice(0, -1).map((m) => {
          const withPaths = m.attachments?.filter((a) => a.path);
          let content: string | Record<string, string>[] = m.content;
          if (withPaths && withPaths.length > 0) {
            const parts: Record<string, string>[] = [{ type: "text", text: m.content }];
            for (const att of withPaths) {
              if (att.type.startsWith("image/")) {
                parts.push({ type: "image", image: att.path! });
              } else {
                parts.push({ type: "file", file: att.path! });
              }
            }
            content = parts;
          }
          return { role: m.role, content, parts: m.parts };
        });

        const response = await fetch(`${baseUrl}/chat`, {
          method: "POST",
          headers,
          body: JSON.stringify({ messages: requestMessages, session_id: sessionIdRef.current || undefined }),
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

              // Capture session_id from server, don't add as part
              if (type === "session_id" && item.session_id) {
                sessionIdRef.current = item.session_id;
                setSessionId(item.session_id);
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

        // Auto-save session with full messages snapshot
        if (sessionIdRef.current) {
          const sid = sessionIdRef.current;
          const currentMessages = messagesRef.current;
          const firstUserMsg = currentMessages.find((m) => m.role === "user");
          const title = (firstUserMsg?.content || "").slice(0, 100);
          const authH = { "Content-Type": "application/json", ...(await authHeaders()) };
          fetch(`${baseUrl}/sessions/${sid}`, {
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
    const { text, attachments } = lastRequestRef.current;
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
    setTimeout(() => send(text, attachments), 0);
  }, [isStreaming, send]);

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const clear = useCallback(() => {
    abortRef.current?.abort();
    setMessages([]);
    setSessionId(null);
    sessionIdRef.current = null;
  }, []);

  const share = useCallback(async (title: string = "", author?: { name: string; imageUrl?: string }) => {
    const headers = { "Content-Type": "application/json", ...(await authHeaders()) };
    const res = await fetch(`${baseUrl}/share`, {
      method: "POST",
      headers,
      body: JSON.stringify({ messages, title, author }),
    });
    if (!res.ok) throw new Error(`Share failed: ${res.status}`);
    const { path } = await res.json();
    return `${window.location.origin}/shared/${path}`;
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
  }, [baseUrl, authHeaders]);

  const listSessions = useCallback(async () => {
    const headers = await authHeaders();
    const res = await fetch(`${baseUrl}/sessions`, { headers });
    if (!res.ok) return [];
    return res.json();
  }, [baseUrl, authHeaders]);

  const loadSession = useCallback(async (id: string) => {
    abortRef.current?.abort();
    setSessionLoading(true);
    try {
      const headers = await authHeaders();
      const res = await fetch(`${baseUrl}/sessions/${id}`, { headers });
      if (!res.ok) throw new Error(`Load failed: ${res.status}`);
      const session = await res.json();
      const loaded: Message[] = session.messages || [];

      setMessages(loaded);
      setSessionId(id);
      sessionIdRef.current = id;

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
      setSessionLoading(false);
    }
  }, [baseUrl, authHeaders, getToken]);

  const deleteSession = useCallback(async (id: string) => {
    const headers = await authHeaders();
    const res = await fetch(`${baseUrl}/sessions/${id}`, { method: "DELETE", headers });
    if (!res.ok) throw new Error(`Delete failed: ${res.status}`);
    // If we deleted the current session, clear it
    if (sessionIdRef.current === id) {
      abortRef.current?.abort();
      setMessages([]);
      setSessionId(null);
      sessionIdRef.current = null;
    }
  }, [baseUrl, authHeaders]);

  return {
    messages,
    isStreaming,
    sessionLoading,
    sessionId,
    send,
    retry,
    stop,
    clear,
    share,
    listShares,
    deleteShare,
    listSessions,
    loadSession,
    deleteSession,
    setGetToken,
    uploadFile,
    authHeaders,
  };
}
