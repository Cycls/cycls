import { useState, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { t, getLang, setLang } from "../lib/i18n";
import { track } from "../lib/analytics";
import { Icon } from "./icon";
import { AttachmentBody } from "./attachment-body";
import { extTint } from "./canvas-utils";
import type { Attachment } from "../hooks/use-chat";

const MENTION_DEBOUNCE_MS = 150;

// `(?:^|\s)` not `\b`: \b matches between the "f" and "@" of "mf@cycls.com" and
// would open the picker on every email address. Spaces are allowed in the query
// so multi-word filenames are searchable; a double space ends the session.
export function mentionAt(value: string, caret: number) {
  const m = value.slice(0, caret).match(/(?:^|\s)@([^\n@]{0,64})$/);
  if (!m || m[1].includes("  ")) return null;
  return { query: m[1], start: caret - m[1].length - 1 };
}

// A dead session swallows anything that extends the query it died on. A blank
// dead query therefore shuts the session outright — correct for Esc, fatal if
// reached by searching "".
export const mentionSuppressed = (
  mention: { start: number; query: string } | null,
  dead: { start: number; query: string } | null,
) => !!(mention && dead && mention.start === dead.start && mention.query.startsWith(dead.query));

// Render composer text with inserted file mentions wrapped in a light-gray
// highlight. Lives behind a transparent-text-area as an aligned backdrop —
// a <textarea> can't style substrings itself.
function highlightMentions(text: string, mentions: string[]) {
  if (!mentions.length) return text;
  const uniq = [...new Set(mentions)].sort((a, b) => b.length - a.length);  // longest first
  const re = new RegExp(`(${uniq.map((m) => m.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "g");
  return text.split(re).map((p, i) =>
    uniq.includes(p) ? <span key={i} className="rounded bg-muted">{p}</span> : <span key={i}>{p}</span>,
  );
}

export function InputBox({
  textareaRef,
  input,
  setInput,
  handleKeyDown,
  handleSubmit,
  isStreaming,
  onStop,
  onOpenFilePicker,
  onOpenFiles,
  attachments,
  onRemoveFile,
  listening,
  transcribing,
  startMic,
  stopMic,
  cancelMic,
  voice,
  onFilesAdded,
  onMentionSearch,
  placeholder,
}: {
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
  input: string;
  setInput: (v: string) => void;
  handleKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  handleSubmit: (overrideText?: string) => void;
  isStreaming: boolean;
  onStop: () => void;
  onOpenFilePicker?: () => void;
  onOpenFiles?: () => void;
  attachments?: Attachment[];
  onRemoveFile?: (index: number) => void;
  listening: boolean;
  transcribing: boolean;
  startMic: () => void;
  stopMic: () => void;
  cancelMic: () => void;
  voice?: boolean;
  onFilesAdded?: (files: File[]) => void;
  onMentionSearch?: (query: string) => Promise<{ name: string; path: string }[]>;
  placeholder?: string;
}) {
  const [dragOver, setDragOver] = useState(false);

  // ---- @-mention file picker ----
  const [mention, setMention] = useState<{ query: string; start: number } | null>(null);
  // The query that came back with nothing, and the "@" it belonged to. Anything
  // extending it is dead too, so typing a sentence containing "@" costs one
  // request rather than one per character — but backspacing to a shorter query
  // that did have hits revives the picker. An empty query means the whole
  // session is shut (Esc).
  const [dead, setDead] = useState<{ start: number; query: string } | null>(null);
  const [results, setResults] = useState<{ name: string; path: string }[]>([]);
  const [activeIdx, setActiveIdx] = useState(0);
  const [mentions, setMentions] = useState<string[]>([]);   // inserted paths → highlighted
  const backdropRef = useRef<HTMLDivElement>(null);

  // Drop highlights whose text no longer appears (edited/sent).
  useEffect(() => {
    setMentions((ms) => ms.filter((m) => input.includes(m)));
  }, [input]);

  const detectMention = (value: string, caret: number) => {
    const next = mentionAt(value, caret);
    setMention((prev) =>
      !next ? null
        : prev && prev.start === next.start && prev.query === next.query ? prev
        : next);
  };

  const suppressed = mentionSuppressed(mention, dead);

  useEffect(() => {
    if (!mention || suppressed) setResults([]);
  }, [mention, suppressed]);

  useEffect(() => {
    if (!mention || suppressed || !onMentionSearch) return;
    let cancelled = false;
    const timer = setTimeout(() => {
      onMentionSearch(mention.query).then((r) => {
        if (cancelled) return;
        setResults(r);
        setActiveIdx(0);
        // Only a query that actually searched for something may latch. Latching
        // on "" would suppress the whole session, since every query extends it.
        if (!r.length && mention.query.trim()) setDead({ start: mention.start, query: mention.query });
      });
    }, MENTION_DEBOUNCE_MS);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [mention?.query, mention?.start, suppressed, onMentionSearch]);

  const selectMention = (file: { name: string; path: string }) => {
    if (!mention) return;
    const caret = textareaRef.current?.selectionStart ?? input.length;
    const next = input.slice(0, mention.start) + file.path + " " + input.slice(caret);
    setInput(next);
    setMentions((ms) => (ms.includes(file.path) ? ms : [...ms, file.path]));
    setDead(null);
    setMention(null);
    setResults([]);
    const pos = mention.start + file.path.length + 1;
    requestAnimationFrame(() => {
      textareaRef.current?.focus();
      textareaRef.current?.setSelectionRange(pos, pos);
    });
  };

  const onChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    detectMention(e.target.value, e.target.selectionStart ?? e.target.value.length);
  };

  const onSelect = (e: React.SyntheticEvent<HTMLTextAreaElement>) => {
    const el = e.currentTarget;
    detectMention(el.value, el.selectionStart ?? el.value.length);
  };

  // Intercept nav keys while the picker is open; otherwise normal handling.
  const onKeyDownInternal = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (mention && results.length) {
      if (e.key === "ArrowDown") { e.preventDefault(); setActiveIdx((i) => (i + 1) % results.length); return; }
      if (e.key === "ArrowUp") { e.preventDefault(); setActiveIdx((i) => (i - 1 + results.length) % results.length); return; }
      if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); selectMention(results[activeIdx]); return; }
      if (e.key === "Escape") { e.preventDefault(); setDead({ start: mention.start, query: "" }); setMention(null); return; }
    }
    handleKeyDown(e);
  };

  // Paste images / files from the clipboard → attach them.
  const onPaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    if (!onFilesAdded) return;
    const files = Array.from(e.clipboardData.items)
      .filter((it) => it.kind === "file")
      .map((it) => it.getAsFile())
      .filter((f): f is File => !!f);
    if (files.length) { e.preventDefault(); onFilesAdded(files); }
  };

  return (
    <motion.div
      layoutId="chat-input"
      className={`border bg-background rounded-3xl p-2 shadow-sm cursor-text ${dragOver ? "border-primary" : "border-border"}`}
      onClick={() => textareaRef.current?.focus()}
      transition={{ type: "spring", stiffness: 200, damping: 25 }}
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        if (onFilesAdded && e.dataTransfer.files.length) {
          onFilesAdded(Array.from(e.dataTransfer.files));
        }
      }}
    >
      {/* File previews */}
      <AnimatePresence initial={false}>
        {attachments && attachments.length > 0 && (
          <motion.div
            key="files-list"
            initial={{ height: 0 }}
            animate={{ height: "auto" }}
            exit={{ height: 0 }}
            transition={{ type: "spring", duration: 0.2, bounce: 0 }}
            className="overflow-hidden"
          >
            <div className="flex flex-row overflow-x-auto px-2 pt-3 pb-2 gap-2">
              <AnimatePresence initial={false}>
                {attachments.map((file, index) => (
                  <motion.div
                    key={file.name + index}
                    initial={{ width: 0, opacity: 0 }}
                    animate={{ width: 180, opacity: 1 }}
                    exit={{ width: 0, opacity: 0 }}
                    transition={{ type: "spring", duration: 0.2, bounce: 0 }}
                    className="relative shrink-0"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <div className={`flex w-full items-center gap-3 rounded-2xl p-2 pr-3 transition-colors border ${file.status === "error" ? "border-red-400/60 bg-red-50 dark:bg-red-950/20" : "border-border bg-background hover:bg-secondary/50"}`}>
                      <AttachmentBody attachment={file} />
                    </div>
                    {onRemoveFile && (
                      <button
                        type="button"
                        onClick={() => onRemoveFile(index)}
                        className="absolute top-0 right-0 z-10 flex size-5 translate-x-1/4 -translate-y-1/4 items-center justify-center rounded-full border-2 border-background bg-foreground text-background transition cursor-pointer"
                        aria-label="Remove file"
                      >
                        <Icon name="x" className="size-3" strokeWidth={2.5} />
                      </button>
                    )}
                  </motion.div>
                ))}
              </AnimatePresence>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="relative">
        {/* @-mention file picker — floats above the textarea */}
        <AnimatePresence>
          {mention && results.length > 0 && (
            <motion.div
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 6 }}
              transition={{ duration: 0.12 }}
              dir="ltr"
              onClick={(e) => e.stopPropagation()}
              className="absolute bottom-full left-2 right-2 mb-2 z-50 max-h-56 overflow-y-auto rounded-xl border border-border bg-background shadow-lg py-1"
            >
              <div className="px-3 pb-1 pt-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground/70">{t("files")}</div>
              {results.map((f, i) => (
                <button
                  key={f.path}
                  type="button"
                  onMouseEnter={() => setActiveIdx(i)}
                  onMouseDown={(e) => { e.preventDefault(); selectMention(f); }}
                  className={`flex w-full items-center gap-2 px-3 py-1.5 text-sm cursor-pointer ${i === activeIdx ? "bg-secondary text-foreground" : "text-muted-foreground hover:bg-secondary/60"}`}
                >
                  <span className="size-1.5 shrink-0 rounded-full"
                        style={{ backgroundColor: extTint(f.name) || "var(--color-muted-foreground)" }} />
                  <span className="truncate">
                    {f.path.lastIndexOf("/") >= 0 && (
                      <span className="text-muted-foreground/60">{f.path.slice(0, f.path.lastIndexOf("/") + 1)}</span>
                    )}
                    {f.name}
                  </span>
                </button>
              ))}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Backdrop that paints the mention highlights, aligned behind the
            transparent-background textarea. Same box metrics so text lines up. */}
        <div
          ref={backdropRef}
          aria-hidden
          dir={input ? "auto" : getLang() === "ar" ? "rtl" : "ltr"}
          className="pointer-events-none absolute inset-0 z-0 overflow-hidden whitespace-pre-wrap break-words px-3 py-2.5 leading-6 text-transparent"
        >
          {highlightMentions(input, mentions)}
        </div>
        <textarea
          ref={textareaRef}
          dir={input ? "auto" : getLang() === "ar" ? "rtl" : "ltr"}
          value={input}
          onChange={onChange}
          onSelect={onSelect}
          onKeyDown={onKeyDownInternal}
          onPaste={onPaste}
          onScroll={(e) => { if (backdropRef.current) backdropRef.current.scrollTop = e.currentTarget.scrollTop; }}
          placeholder={placeholder || t("sendMessage")}
          rows={1}
          className="relative z-10 w-full min-h-[44px] max-h-[240px] resize-none bg-transparent px-3 py-2.5 leading-6 text-foreground placeholder:text-muted-foreground focus:outline-none overflow-y-auto"
        />
      </div>

      {/* Actions row: paperclip left, send right */}
      <div className="flex items-center justify-between px-1 pt-1" dir="ltr">
        <div className="relative flex items-center gap-0.5">
          {(onOpenFilePicker || onOpenFiles) && (
            <AttachMenu onOpenFilePicker={onOpenFilePicker} onOpenFiles={onOpenFiles} disabled={isStreaming} />
          )}
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              const next = getLang() === "en" ? "ar" : "en";
              setLang(next);
              track("language_changed", { to: next, source: "composer" });
            }}
            disabled={isStreaming}
            className={`flex h-8 items-center justify-center rounded-full px-2.5 transition text-xs font-semibold ${isStreaming ? "text-muted-foreground opacity-30 cursor-not-allowed" : "text-muted-foreground hover:text-foreground hover:bg-secondary cursor-pointer"}`}
            aria-label="Toggle language"
          >
            {getLang() === "en" ? "عربي" : "En"}
          </button>
        </div>
        <div className="flex items-center gap-1">
          {voice && <MicButton listening={listening} transcribing={transcribing} disabled={isStreaming} onStart={startMic} onStop={stopMic} onCancel={cancelMic} />}
          {/* A filled composer stays sendable mid-run — the message queues and
              fires when the reply finishes — so send and stop sit side by
              side while streaming. Empty composer, streaming: stop only. */}
          {(!isStreaming || input.trim()) && (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); handleSubmit(); }}
              disabled={!input.trim() || attachments?.some((a) => a.status === "uploading")}
              className={`flex size-8 items-center justify-center rounded-full transition cursor-pointer disabled:opacity-30 ${isStreaming ? "border border-border text-foreground hover:bg-secondary" : "bg-foreground text-background hover:opacity-80"}`}
              aria-label={isStreaming ? t("queueMessage") : "Send"}
              title={isStreaming ? t("queueMessage") : undefined}
            >
              <svg className="size-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 12l7-7 7 7M12 5v14" />
              </svg>
            </button>
          )}
          {isStreaming && (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onStop(); }}
              className="flex size-8 items-center justify-center rounded-full bg-foreground text-background hover:opacity-80 transition cursor-pointer"
              aria-label="Stop"
            >
              <svg className="size-5" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2" /></svg>
            </button>
          )}
        </div>
      </div>
    </motion.div>
  );
}

function MicButton({ listening, transcribing, disabled, onStart, onStop, onCancel }: { listening: boolean; transcribing: boolean; disabled: boolean; onStart: () => void; onStop: () => void; onCancel: () => void }) {
  return (
    <button
      type="button"
      onClick={(e) => { e.stopPropagation(); transcribing ? onCancel() : listening ? onStop() : onStart(); }}
      disabled={disabled && !transcribing}
      className={`flex size-8 items-center justify-center rounded-full transition ${disabled && !listening && !transcribing ? "text-muted-foreground opacity-30 cursor-not-allowed" : listening ? "bg-foreground text-background animate-pulse cursor-pointer" : transcribing ? "text-muted-foreground hover:text-foreground cursor-pointer" : "text-muted-foreground hover:text-foreground hover:bg-secondary cursor-pointer"}`}
      aria-label={listening ? "Stop recording" : transcribing ? "Cancel transcription" : "Start recording"}
    >
      <svg className={`size-5${transcribing ? " animate-pulse [animation-duration:0.9s]" : ""}`} fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3z" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M19 10v2a7 7 0 01-14 0v-2" />
        <line x1="12" y1="19" x2="12" y2="23" strokeLinecap="round" />
        <line x1="8" y1="23" x2="16" y2="23" strokeLinecap="round" />
      </svg>
    </button>
  );
}

function AttachMenu({ onOpenFilePicker, onOpenFiles, disabled }: { onOpenFilePicker?: () => void; onOpenFiles?: () => void; disabled?: boolean }) {
  const [open, setOpen] = useState(false);
  const btnClass = `flex size-8 items-center justify-center rounded-2xl transition ${disabled ? "text-muted-foreground opacity-30 cursor-not-allowed" : "text-muted-foreground hover:text-foreground hover:bg-secondary/80 cursor-pointer"}`;

  if (onOpenFilePicker && !onOpenFiles) {
    return (
      <button type="button" onClick={(e) => { e.stopPropagation(); onOpenFilePicker(); }} disabled={disabled} className={btnClass} aria-label="Attach file">
        <Icon name="paperclip" className="size-5" />
      </button>
    );
  }

  return (
    <>
      <button type="button" onClick={(e) => { e.stopPropagation(); if (!disabled) setOpen(!open); }} disabled={disabled} className={btnClass} aria-label="Attach">
        <Icon name="paperclip" className="size-5" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute left-0 bottom-full z-50 mb-2 w-44 rounded-lg border border-border bg-background shadow-lg py-1">
            {onOpenFilePicker && (
              <button
                onClick={(e) => { e.stopPropagation(); setOpen(false); onOpenFilePicker(); }}
                className="flex w-full items-center gap-2.5 px-3 py-2 text-sm text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
              >
                <Icon name="upload" className="size-4" />
                {t("uploadFile")}
              </button>
            )}
            {onOpenFiles && (
              <button
                onClick={(e) => { e.stopPropagation(); setOpen(false); onOpenFiles(); }}
                className="flex w-full items-center gap-2.5 px-3 py-2 text-sm text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
              >
                <Icon name="folder" className="size-4" />
                {t("browseFiles")}
              </button>
            )}
          </div>
        </>
      )}
    </>
  );
}
