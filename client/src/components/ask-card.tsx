import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Icon } from "./icon";
import { tIn, langOf } from "../lib/i18n";
import { cn } from "../lib/utils";

export type AskQuestion = {
  question: string;
  header?: string;
  options: { label: string; description?: string }[];
  multi: boolean;
};

export function AskCard({ questions, onSubmit, onDismiss }: {
  questions: AskQuestion[];
  onSubmit: (lines: string[]) => void;
  onDismiss: () => void;
}) {
  const [picked, setPicked] = useState<string[][]>(() => questions.map(() => []));
  const [typed, setTyped] = useState<string[]>(() => questions.map(() => ""));
  const [step, setStep] = useState(0);

  const q = questions[step];
  // Everything in this card except the hints is the model's text, written in
  // the user's language. Follow that rather than the UI toggle, or an Arabic
  // question renders with an English instruction under it and an LTR input —
  // the browser's locale decides the chrome, and it needn't match the chat.
  const lang = langOf(q.question);
  const rtl = lang === "ar";
  const isLast = step === questions.length - 1;
  const open = q.options.length === 0;
  // Multi-select and open questions need an explicit commit; a single-select
  // tap commits itself.
  const needsButton = q.multi || open;
  const answered = open ? typed[step].trim().length > 0 : picked[step].length > 0;

  // Answers in the options' own order, not click order — the card's order is
  // the one the user saw. Several questions come back labelled by header; one
  // sends the bare answer, which reads like a typed message. Takes the arrays
  // explicitly so a tap can commit its own value without waiting for state.
  const buildLines = (p: string[][], ty: string[]) =>
    questions.map((qq, i) => {
      const answer = qq.options.length === 0
        ? ty[i].trim()
        : qq.options.filter((o) => p[i].includes(o.label)).map((o) => o.label).join(", ");
      if (!answer) return null;   // skipped questions simply don't appear
      return questions.length === 1 ? answer : `${qq.header || qq.question}: ${answer}`;
    }).filter((l): l is string => l !== null);

  const send = (p: string[][], ty: string[]) => {
    const lines = buildLines(p, ty);
    if (lines.length) onSubmit(lines);
  };

  // Skipping is the card honouring its own promise: the options are shortcuts,
  // not a gate. An unanswered question is dropped from the reply, so the model
  // sees only what the user actually chose. Skipping the last one still sends
  // the earlier answers; skipping every one leaves nothing to say, so the card
  // just closes.
  const skip = () => {
    if (!isLast) { setStep((n) => n + 1); return; }
    const lines = buildLines(picked, typed);
    if (lines.length) onSubmit(lines);
    else onDismiss();
  };

  const advance = (p: string[][], ty: string[]) => {
    if (isLast) send(p, ty);
    else setStep((n) => n + 1);
  };

  const choose = (label: string) => {
    const next = picked.map((p, i) =>
      i !== step ? p
        : q.multi ? (p.includes(label) ? p.filter((l) => l !== label) : [...p, label])
        : [label]);
    setPicked(next);
    if (!q.multi) advance(next, typed);   // a single-select tap is the answer
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.15 }}
      className="mb-2 px-1"
    >
      <div dir={rtl ? "rtl" : "ltr"} className="rounded-2xl border border-border bg-background shadow-sm">
        <div className="flex items-start gap-2 px-3.5 pt-2.5 pb-1">
          <div className="min-w-0 flex-1">
            {(q.header || questions.length > 1) && (
              <p dir="auto" className="mb-0.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground/70">
                {q.header}
                {q.header && questions.length > 1 ? " · " : ""}
                {questions.length > 1 ? `${step + 1}/${questions.length}` : ""}
              </p>
            )}
            <p dir="auto" className="text-[15px] font-medium leading-snug text-foreground">{q.question}</p>
            {!open && (
              <p dir="auto" className="mt-0.5 text-xs leading-snug text-muted-foreground">
                {q.multi ? tIn(lang, "selectMany") : tIn(lang, "selectOne")}
              </p>
            )}
          </div>
          <button
            onClick={onDismiss}
            className="-me-1 shrink-0 rounded-full p-1 text-muted-foreground/60 hover:bg-secondary hover:text-foreground transition-colors cursor-pointer"
            aria-label={tIn(lang, "dismiss")}
          >
            <Icon name="x" className="size-3" />
          </button>
        </div>

        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={step}
            initial={{ opacity: 0, x: 6 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -6 }}
            transition={{ duration: 0.12 }}
          >
            {open ? (
              <div className="px-3.5 py-1.5">
                <input
                  autoFocus
                  dir={typed[step] ? "auto" : rtl ? "rtl" : "ltr"}
                  value={typed[step]}
                  onChange={(e) => setTyped((cur) => cur.map((v, i) => (i === step ? e.target.value : v)))}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && answered) { e.preventDefault(); advance(picked, typed); }
                  }}
                  placeholder={tIn(lang, "typeAnswer")}
                  className="w-full rounded-xl border border-border bg-background px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-foreground/30"
                />
              </div>
            ) : (
              <div className="flex flex-col gap-1.5 px-3.5 py-1.5">
                {q.options.map((o) => {
                  const on = picked[step].includes(o.label);
                  return (
                    <button
                      key={o.label}
                      onClick={() => choose(o.label)}
                      {...(q.multi ? { role: "checkbox", "aria-checked": on } : {})}
                      dir="auto"
                      className={cn(
                        "flex w-full items-start gap-2.5 rounded-xl border px-3 py-2 text-start transition-colors cursor-pointer",
                        on ? "border-foreground/30 bg-secondary/50"
                           : "border-border hover:border-foreground/20 hover:bg-secondary/40",
                      )}
                    >
                      {q.multi && (
                        <span
                          className={cn(
                            "mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-[5px] border transition-colors",
                            on ? "border-foreground bg-foreground text-background" : "border-border",
                          )}
                        >
                          {on && <Icon name="check" className="size-2.5" strokeWidth={3} />}
                        </span>
                      )}
                      <span className="min-w-0">
                        <span className="block text-sm leading-snug text-foreground">{o.label}</span>
                        {o.description && (
                          <span className="block text-xs leading-snug text-muted-foreground">{o.description}</span>
                        )}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </motion.div>
        </AnimatePresence>

        {/* Always present: even a single-select step, which commits by tap and
            needs no Next, has to offer a way past. */}
        <div className="flex items-center justify-between px-3.5 pb-2.5 pt-0.5">
          {step > 0 ? (
            <button
              onClick={() => setStep((n) => n - 1)}
              className="rounded-full px-2 py-1 text-xs text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors cursor-pointer"
            >
              {tIn(lang, "back")}
            </button>
          ) : <span />}
          <div className="flex items-center gap-1">
            <button
              onClick={skip}
              className="rounded-full px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors cursor-pointer"
            >
              {tIn(lang, "skip")}
            </button>
            {needsButton && (
              <button
                onClick={() => advance(picked, typed)}
                disabled={!answered}
                className="rounded-full bg-foreground px-3.5 py-1.5 text-xs font-medium text-background transition hover:opacity-80 disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
              >
                {isLast ? tIn(lang, "submit") : tIn(lang, "next")}
                {q.multi && picked[step].length > 1 ? ` · ${picked[step].length}` : ""}
              </button>
            )}
          </div>
        </div>
      </div>
    </motion.div>
  );
}

// The one suggested follow-up (the agent's `suggest` tool) — a single chip
// above the composer. Click sends it; ArrowUp (empty composer) pulls it in
// for editing; it clears on any send.
