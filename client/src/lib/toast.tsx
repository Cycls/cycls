// Top-center toast for transient notifications (API errors are the main user).
// Provider lives at the App root; `useToast()` fires from anywhere in the tree.
import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "framer-motion";

type Kind = "error" | "info";
type Action = { label: string; onClick: () => void };
type Toast = { id: number; kind: Kind; text: string; action?: Action };

// Default to a no-op so callers (and tests) can use the hook even when no
// provider is mounted — they just won't render any toast UI.
const ToastContext = createContext<{ show: (kind: Kind, text: string, opts?: { action?: Action; ttl?: number }) => void }>({ show: () => {} });

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const counter = useRef(0);
  const show = useCallback((kind: Kind, text: string, opts?: { action?: Action; ttl?: number }) => {
    const id = ++counter.current;
    setToasts((prev) => [...prev, { id, kind, text, action: opts?.action }]);
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), opts?.ttl ?? 4000);
  }, []);
  return (
    <ToastContext.Provider value={{ show }}>
      {children}
      {createPortal(
        <div className="fixed top-4 left-1/2 -translate-x-1/2 z-[120] flex flex-col gap-2 items-center pointer-events-none">
          <AnimatePresence>
            {toasts.map((t) => (
              <motion.div
                key={t.id}
                initial={{ opacity: 0, y: -10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                className="flex items-center gap-3 rounded-lg border border-border bg-background shadow-lg px-3 py-2 pointer-events-auto"
              >
                <span className={`text-xs ${t.kind === "error" ? "text-red-500" : "text-foreground"}`}>{t.text}</span>
                {t.action && (
                  <button
                    onClick={() => { t.action!.onClick(); setToasts((prev) => prev.filter((x) => x.id !== t.id)); }}
                    className="text-xs font-medium text-accent hover:underline cursor-pointer"
                  >
                    {t.action.label}
                  </button>
                )}
              </motion.div>
            ))}
          </AnimatePresence>
        </div>,
        document.body,
      )}
    </ToastContext.Provider>
  );
}

export function useToast() {
  const { show } = useContext(ToastContext);
  // Memo so callers using these in useCallback deps keep stable references.
  return useMemo(() => ({
    error: (text: string) => show("error", text),
    info: (text: string) => show("info", text),
    // A reversible action: 10s to change your mind, then the Trash tab.
    undo: (text: string, label: string, onUndo: () => void) => show("info", text, { action: { label, onClick: onUndo }, ttl: 10_000 }),
  }), [show]);
}
