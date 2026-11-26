import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Star } from "./cycls-star";
import { ext, extTint, tileExt } from "./canvas-utils";
import { getLang } from "../lib/i18n";
import { cn } from "../lib/utils";

// What to make, under the composer (the Super mockup's format row): the file types the examples come in, as the
// tiles their cards carry. A tile opens into its name while hovered, the chosen one stays open; choosing one shows
// that type's examples and has the composer ask that type's question.

export interface FormatOption { key: string; text: string; count: number; format?: string }

// The types, their names, and the question the composer asks for each (the mockup's own where it has one).
const FORMATS: Record<string, { en: string; ar?: string; ext: string; tile?: string; hint?: { en: string; ar: string } }> = {
  pdf: { en: "PDF", ar: "ملف PDF", ext: "pdf", hint: { en: "What should your report cover?", ar: "وش موضوع التقرير اللي في بالك؟" } },
  pptx: { en: "PowerPoint", ar: "عرض تقديمي", ext: "pptx", hint: { en: "What are the slides about, and who are they for?", ar: "وش موضوع العرض، ولمين بتقدّمه؟" } },
  docx: { en: "Word", ar: "مستند Word", ext: "docx", hint: { en: "What are you writing, and who will read it?", ar: "وش ودّك تكتب، ومين بيقراه؟" } },
  xlsx: { en: "Excel", ar: "جدول Excel", ext: "xlsx", hint: { en: "What do you want to calculate or track?", ar: "وش ودّك تحسب أو ترتّب في الجدول؟" } },
  md: { en: "Document", ar: "مستند", ext: "md", hint: { en: "What are you writing, and who will read it?", ar: "وش ودّك تكتب، ومين بيقراه؟" } },
  html: { en: "Interactive page", ar: "صفحة تفاعلية", ext: "html", hint: { en: "What should the page show, and who will use it?", ar: "وش تبي الصفحة تعرض، ومين بيستخدمها؟" } },
  fig: { en: "Design", ar: "تصميم", ext: "fig", hint: { en: "What should we design, and where will it be used?", ar: "وش التصميم اللي في بالك، ووين بتستخدمه؟" } },
  image: { en: "Image", ar: "صورة", ext: "png", tile: "IMG", hint: { en: "What image do you have in mind?", ar: "وش فكرة الصورة اللي في بالك؟" } },
  video: { en: "Video", ar: "فيديو", ext: "mp4", tile: "VIDEO", hint: { en: "What should the video show?", ar: "وش تبي الفيديو يعرض؟" } },
  other: { en: "File", ar: "ملف", ext: "", tile: "FILE" },
};
const BY_EXT: Record<string, string> = {
  ppt: "pptx", key: "pptx", doc: "docx", xls: "xlsx", csv: "xlsx", htm: "html", markdown: "md",
  png: "image", jpg: "image", jpeg: "image", webp: "image", gif: "image", mp4: "video", mov: "video", webm: "video",
};
export const formatOf = (item: { kind?: string | null; video?: string | null; file?: { name: string } | null }) => {
  if (item.video) return "video";
  if (item.kind) return item.kind in FORMATS ? item.kind : "other";
  const e = item.file ? ext(item.file.name) : "";
  return BY_EXT[e] || (e in FORMATS ? e : "other");
};
export const formatName = (f: string) => {
  const n = FORMATS[f] || FORMATS.other;
  return (getLang() === "ar" && n.ar) || n.en;
};
export const formatHint = (f: string) => {
  const h = FORMATS[f]?.hint;
  return h ? (getLang() === "ar" ? h.ar : h.en) : "";
};

// A file type as cycls.com draws it (components/ui/file-badge.tsx): the extension washed in its colour. `name` is a
// file name for the colour, `label` the word in the tile.
export function TypeTile({ name, label, size = 28, className }: { name: string; label: string; size?: number; className?: string }) {
  const tint = extTint(name) || "#8e8e93";
  return (
    <span
      dir="ltr"
      className={cn("inline-flex shrink-0 items-center justify-center border font-semibold leading-none bg-[color-mix(in_srgb,var(--tint)_12%,#fff)] dark:bg-[color-mix(in_srgb,var(--tint)_18%,#0f0f0f)]", className)}
      style={{
        ["--tint" as string]: tint, color: tint, width: size, height: size, borderRadius: size * 0.218,
        borderColor: `color-mix(in srgb, ${tint} 45%, transparent)`,
        fontSize: Math.round(((size * 0.235 * 4) / Math.max(4, label.length)) * 10) / 10,
      }}
    >
      {label}
    </span>
  );
}

const formatTile = (f: string) => {
  const n = FORMATS[f] || FORMATS.other;
  const name = n.ext ? `f.${n.ext}` : "";
  return { name, label: n.tile || (tileExt(name) || "file").slice(0, 6).toUpperCase() };
};

const spring = { type: "spring", stiffness: 420, damping: 32 } as const;

export function FormatTiles({ value, options, onChange }: { value: string; options: FormatOption[]; onChange: (key: string) => void }) {
  return (
    <div className="flex w-full justify-center">
      <div role="group" className="flex max-w-full items-center gap-1 overflow-x-auto scrollbar-none px-2 py-1">
        {options.map((o) => <TileChip key={o.key} option={o} on={o.key === value} onClick={() => onChange(o.key)} />)}
      </div>
    </div>
  );
}

function TileChip({ option, on, onClick }: { option: FormatOption; on: boolean; onClick: () => void }) {
  const [hover, setHover] = useState(false);
  const open = on || hover;
  const tile = option.format ? formatTile(option.format) : null;
  return (
    <motion.button
      layout
      transition={spring}
      aria-pressed={on}
      aria-label={option.text}
      onPointerEnter={(e) => { if (e.pointerType === "mouse") setHover(true); }}
      onPointerLeave={() => setHover(false)}
      onFocus={() => setHover(true)}
      onBlur={() => setHover(false)}
      onClick={onClick}
      className={cn("flex shrink-0 cursor-pointer items-center rounded-[10px] border p-1 transition-colors",
        on ? "border-foreground/25 bg-secondary" : "border-transparent hover:bg-secondary/60")}
    >
      {tile ? (
        <TypeTile name={tile.name} label={tile.label} size={26} />
      ) : (
        <span className="flex size-[26px] items-center justify-center rounded-[6px] border border-border bg-background text-foreground"><Star size={12} /></span>
      )}
      <AnimatePresence initial={false}>
        {open && (
          <motion.span
            initial={{ width: 0, opacity: 0 }}
            animate={{ width: "auto", opacity: 1 }}
            exit={{ width: 0, opacity: 0 }}
            transition={{ duration: 0.18 }}
            className="flex items-center gap-1.5 overflow-hidden whitespace-nowrap ps-2 pe-1.5 text-sm"
          >
            <bdi className="font-medium text-foreground">{option.text}</bdi>
            <span className="text-xs tabular-nums text-muted-foreground">{option.count}</span>
          </motion.span>
        )}
      </AnimatePresence>
    </motion.button>
  );
}
