import { useEffect, useRef, useState } from "react";
import { t } from "../lib/i18n";

// `align`: "start"/"end" are logical (settings rows); "right" pins to the
// physical right edge — for the user-menu panel, which hugs the screen's
// right side in both LTR and RTL, so the picker can only extend leftward.
const ALIGN = { start: "start-0", end: "end-0", right: "right-0" };

// Full emoji picker (search, categories, skin tones) — the same vocabulary as
// the mobile app's native keyboard; the server validates single-emoji anyway.
// emoji-mart's vanilla web component: framework-agnostic (React-19 safe) and
// lazy-loaded, so its data ships only when a picker actually opens.
export function EmojiPicker({ onPick, onClear, onClose, align = "start" }: {
  onPick: (emoji: string) => void;
  onClear?: () => void;
  onClose: () => void;
  align?: keyof typeof ALIGN;
}) {
  const host = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    Promise.all([import("emoji-mart"), import("@emoji-mart/data")]).then(([mart, data]) => {
      if (!alive || !host.current) return;
      setLoading(false);
      new (mart as any).Picker({
        parent: host.current,
        data: (data as any).default,
        onEmojiSelect: (e: { native: string }) => onPick(e.native),
        theme: document.body.classList.contains("dark") ? "dark" : "light",
        previewPosition: "none",
        skinTonePosition: "search",
        maxFrequentRows: 1,
        perLine: 8,
        emojiButtonSize: 32,
        emojiSize: 20,
      });
    });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <>
      <div className="fixed inset-0 z-40" onClick={(e) => { e.stopPropagation(); onClose(); }} />
      <div className={`absolute z-50 top-full mt-1 ${ALIGN[align]} overflow-hidden rounded-lg border border-border bg-background shadow-lg`}>
        {loading && <div className="flex h-24 w-72 items-center justify-center text-sm text-muted-foreground">…</div>}
        <div ref={host} />
        {onClear && (
          <button
            onClick={(ev) => { ev.stopPropagation(); onClear(); }}
            className="w-full cursor-pointer border-t border-border px-3 py-2 text-start text-xs text-muted-foreground transition-colors hover:bg-secondary/80 hover:text-foreground"
          >
            {t("remove")}
          </button>
        )}
      </div>
    </>
  );
}
