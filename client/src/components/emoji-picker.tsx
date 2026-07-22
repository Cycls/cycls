import { t } from "../lib/i18n";

const EMOJI = [
  "🚀", "🔬", "📊", "📁", "🎨", "✍️", "💼", "🧠",
  "⚙️", "🌍", "📚", "💡", "🔥", "⭐", "🎯", "🧪",
  "💰", "📈", "🛠️", "🗂️", "🧭", "🏗️", "🤝", "🔒",
  "🌱", "🎓", "🏆", "❤️", "☕", "🎧", "📝", "📌",
  "🧩", "🎬", "📷", "🌙", "⚡", "🦾", "🤖", "🎁",
];

// Notion-style emoji picker: a small curated grid + optional Remove.
// Renders as an absolutely-positioned card; the parent supplies a
// `relative` container. A fixed backdrop closes it on outside click.
export function EmojiPicker({ onPick, onClear, onClose, align = "start" }: {
  onPick: (emoji: string) => void;
  onClear?: () => void;
  onClose: () => void;
  align?: "start" | "end";
}) {
  return (
    <>
      <div className="fixed inset-0 z-40" onClick={(e) => { e.stopPropagation(); onClose(); }} />
      <div className={`absolute z-50 top-full mt-1 ${align === "start" ? "start-0" : "end-0"} w-60 rounded-lg border border-border bg-background p-2 shadow-lg`}>
        <div className="grid grid-cols-8 gap-0.5">
          {EMOJI.map((e) => (
            <button
              key={e}
              onClick={(ev) => { ev.stopPropagation(); onPick(e); }}
              className="flex size-7 cursor-pointer items-center justify-center rounded text-base hover:bg-secondary/80"
            >
              {e}
            </button>
          ))}
        </div>
        {onClear && (
          <button
            onClick={(ev) => { ev.stopPropagation(); onClear(); }}
            className="mt-1.5 w-full cursor-pointer rounded px-2 py-1 text-start text-xs text-muted-foreground hover:bg-secondary/80 hover:text-foreground"
          >
            {t("remove")}
          </button>
        )}
      </div>
    </>
  );
}
