import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { t, getLang, setLang } from "../lib/i18n";
import { track } from "../lib/posthog";
import { Icon } from "./icon";
import { AttachmentBody } from "./attachment-body";
import type { Attachment } from "../hooks/use-chat";

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
  placeholder?: string;
}) {
  const [dragOver, setDragOver] = useState(false);

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

      <textarea
        ref={textareaRef}
        dir={input ? "auto" : getLang() === "ar" ? "rtl" : "ltr"}
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder || t("sendMessage")}
        rows={1}
        className="w-full min-h-[44px] max-h-[240px] resize-none bg-transparent px-3 py-2.5 text-foreground placeholder:text-muted-foreground focus:outline-none overflow-y-auto"
      />

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
          {isStreaming ? (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onStop(); }}
              className="flex size-8 items-center justify-center rounded-full bg-foreground text-background hover:opacity-80 transition cursor-pointer"
              aria-label="Stop"
            >
              <svg className="size-5" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2" /></svg>
            </button>
          ) : (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); handleSubmit(); }}
              disabled={!input.trim() || attachments?.some((a) => a.status === "uploading")}
              className="flex size-8 items-center justify-center rounded-full bg-foreground text-background hover:opacity-80 disabled:opacity-30 transition cursor-pointer"
              aria-label="Send"
            >
              <svg className="size-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 12l7-7 7 7M12 5v14" />
              </svg>
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
