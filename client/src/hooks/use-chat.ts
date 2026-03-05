import { useState, useCallback, useRef } from "react";

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
  label?: string;
  action?: string;
  payload?: Record<string, unknown>;
  session_id?: string;
}

export interface Message {
  role: "user" | "assistant";
  content: string;
  parts?: Part[];
}

export interface AppConfig {
  header?: string;
  intro?: string;
  title?: string;
  auth?: boolean;
  pk?: string;
}

export function useChat(baseUrl: string = "/api") {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const getTokenRef = useRef<(() => Promise<string | null>) | null>(null);

  const setGetToken = useCallback(
    (fn: () => Promise<string | null>) => {
      getTokenRef.current = fn;
    },
    [],
  );

  const fetchConfig = useCallback(async () => {
    try {
      const res = await fetch(`${baseUrl}/config`);
      const data = await res.json();
      setConfig(data);
      return data as AppConfig;
    } catch {
      return null;
    }
  }, [baseUrl]);

  const send = useCallback(
    async (text: string) => {
      if (isStreaming) return;

      const userMessage: Message = { role: "user", content: text };
      const assistantMessage: Message = {
        role: "assistant",
        content: "",
        parts: [],
      };

      setMessages((prev) => [...prev, userMessage, assistantMessage]);
      setIsStreaming(true);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const headers: Record<string, string> = {
          "Content-Type": "application/json",
        };

        if (getTokenRef.current) {
          const token = await getTokenRef.current();
          if (token) headers["Authorization"] = `Bearer ${token}`;
        }

        // Build request messages (all except the empty assistant we just added)
        const requestMessages = [...messages, userMessage].map((m) => ({
          role: m.role,
          content: m.content,
          parts: m.parts,
        }));

        const response = await fetch(`${baseUrl}/`, {
          method: "POST",
          headers,
          body: JSON.stringify({ messages: requestMessages }),
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
                if (last.role === "assistant") {
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
          if (last.role === "assistant") {
            updated[updated.length - 1] = {
              ...last,
              content: contentText,
              parts: finalParts,
            };
          }
          return updated;
        });
      } catch (err) {
        if ((err as Error).name !== "AbortError") {
          // Add error as callout
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last.role === "assistant") {
              updated[updated.length - 1] = {
                ...last,
                parts: [
                  {
                    type: "callout",
                    callout: `Connection error: ${(err as Error).message}`,
                    style: "error",
                  },
                ],
              };
            }
            return updated;
          });
        }
      } finally {
        setIsStreaming(false);
        abortRef.current = null;
      }
    },
    [messages, isStreaming, baseUrl],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const clear = useCallback(() => {
    setMessages([]);
  }, []);

  return {
    messages,
    isStreaming,
    config,
    send,
    stop,
    clear,
    fetchConfig,
    setGetToken,
  };
}
