import { useState, useRef, useEffect } from "react";
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
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || isStreaming) return;
    setInput("");
    onSend(text);
  };

  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header className="border-b border-[var(--border-color)] p-4">
        <div className="max-w-3xl mx-auto flex items-center justify-between">
          <h1 className="text-lg font-semibold">{title || "Cycls"}</h1>
          <div className="flex items-center gap-2">
            {messages.length > 0 && (
              <button
                onClick={onClear}
                className="text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] px-3 py-1.5 rounded-lg hover:bg-[var(--bg-secondary)] cursor-pointer"
              >
                Clear
              </button>
            )}
            <button
              onClick={() => document.body.classList.toggle("dark")}
              className="p-2 rounded-lg hover:bg-[var(--bg-secondary)] cursor-pointer"
            >
              <svg
                className="w-5 h-5"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"
                />
              </svg>
            </button>
          </div>
        </div>
      </header>

      {/* Messages */}
      <main className="flex-1 overflow-y-auto p-4">
        <div className="max-w-3xl mx-auto space-y-4">
          {messages.length === 0 && (
            <div className="text-center text-[var(--text-secondary)] mt-20">
              <p className="text-lg">Send a message to get started</p>
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
          <div ref={messagesEndRef} />
        </div>
      </main>

      {/* Input */}
      <footer className="border-t border-[var(--border-color)] p-4">
        <form
          onSubmit={handleSubmit}
          className="max-w-3xl mx-auto flex gap-2"
        >
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Send a message..."
            className="flex-1 rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] px-4 py-3 text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]"
          />
          {isStreaming ? (
            <button
              type="button"
              onClick={onStop}
              className="rounded-lg border border-[var(--border-color)] px-6 py-3 font-medium hover:bg-[var(--bg-secondary)] cursor-pointer"
            >
              Stop
            </button>
          ) : (
            <button
              type="submit"
              disabled={!input.trim()}
              className="rounded-lg bg-[var(--accent)] px-6 py-3 text-white font-medium hover:opacity-90 disabled:opacity-50 cursor-pointer"
            >
              Send
            </button>
          )}
        </form>
      </footer>
    </div>
  );
}
