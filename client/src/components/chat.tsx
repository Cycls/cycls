import { useState, useRef, useEffect, useCallback } from "react";
import { useStickToBottom } from "use-stick-to-bottom";
import { MessageBubble } from "./message";
import type { Message } from "../hooks/use-chat";

export function Chat({
  messages,
  isStreaming,
  onSend,
  onStop,
  onClear,
  title,
}: {
  messages: Message[];
  isStreaming: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
  onClear: () => void;
  title?: string;
}) {
  const [input, setInput] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { scrollRef, contentRef } = useStickToBottom();

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

  const handleSubmit = useCallback(() => {
    const text = input.trim();
    if (!text || isStreaming) return;
    setInput("");
    onSend(text);
  }, [input, isStreaming, onSend]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const toggleDark = () => {
    document.body.classList.toggle("dark");
  };

  return (
    <div className="h-screen flex flex-col">
      {/* Header */}
      <header className="pointer-events-none fixed top-0 right-0 left-0 z-50 h-12">
        <div className="pointer-events-auto mx-auto flex h-full max-w-full items-center justify-between px-4 sm:px-6">
          <a href="/" className="flex items-center gap-2 text-foreground hover:opacity-80 transition-opacity">
            <span className="text-sm font-semibold">{title || "Cycls"}</span>
          </a>
          <div className="flex items-center gap-1">
            {messages.length > 0 && (
              <button
                onClick={onClear}
                className="text-muted-foreground hover:text-foreground hover:bg-secondary/80 rounded-lg p-2 transition-colors cursor-pointer"
                aria-label="New chat"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
              </button>
            )}
            <button
              onClick={toggleDark}
              className="text-muted-foreground hover:text-foreground hover:bg-secondary/80 rounded-lg p-2 transition-colors cursor-pointer"
              aria-label="Toggle theme"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
              </svg>
            </button>
          </div>
        </div>
      </header>

      {/* Spacer for fixed header */}
      <div className="shrink-0 h-12" />

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        <div ref={contentRef} className="flex w-full flex-col items-center py-4">
          {messages.length === 0 && (
            <div className="flex-1 flex items-center justify-center pt-32">
              <p className="text-muted-foreground">
                Send a message to get started
              </p>
            </div>
          )}
          {messages.map((msg, i) => (
            <MessageBubble
              key={i}
              message={msg}
              isStreaming={
                isStreaming &&
                i === messages.length - 1 &&
                msg.role === "assistant"
              }
            />
          ))}
        </div>
      </div>

      {/* Input */}
      <div className="shrink-0 px-6 pb-4 pt-2">
        <div className="max-w-3xl mx-auto">
          <div
            className="border border-border bg-background rounded-3xl p-2 shadow-sm cursor-text"
            onClick={() => textareaRef.current?.focus()}
          >
            <div className="flex items-end gap-2">
              <textarea
                ref={textareaRef}
                dir="auto"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Send a message..."
                rows={1}
                className="flex-1 min-h-[44px] max-h-[240px] resize-none bg-transparent px-3 py-2.5 text-foreground placeholder:text-muted-foreground focus:outline-none overflow-y-auto"
              />
              <div className="flex items-center pb-1 pr-1">
                {isStreaming ? (
                  <button
                    type="button"
                    onClick={onStop}
                    className="flex size-9 items-center justify-center rounded-full bg-foreground text-background hover:opacity-80 transition cursor-pointer"
                    aria-label="Stop"
                  >
                    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
                      <rect x="6" y="6" width="12" height="12" rx="2" />
                    </svg>
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={handleSubmit}
                    disabled={!input.trim()}
                    className="flex size-9 items-center justify-center rounded-full bg-foreground text-background hover:opacity-80 disabled:opacity-30 transition cursor-pointer"
                    aria-label="Send"
                  >
                    <svg
                      className="w-4 h-4"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M5 12h14M12 5l7 7-7 7"
                      />
                    </svg>
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
