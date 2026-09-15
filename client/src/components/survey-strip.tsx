import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { Icon } from "./icon";
import { surveysProvider, type Survey, type SurveyQuestion } from "../lib/analytics";
import { useToast } from "../lib/toast";
import { t, tIn, langOf } from "../lib/i18n";
import { cn } from "../lib/utils";

// Surveys as a quiet strip above the composer. The survey is authored and
// targeted on the platform (PostHog today, with the API presentation so its
// own widget stays out of the page); we render one question at a time in the
// follow-up chip's family and send the vendor's own events, so its reports work.
export type { Survey, SurveyQuestion };
export type Question = {
  question: string; open: boolean; multi: boolean;
  options: { label: string; hint?: string }[];
};

const EMOJI: Record<number, string[]> = { 3: ["😞", "😐", "😊"], 5: ["😠", "😞", "😐", "🙂", "😍"] };
const scaleLabels = (q: SurveyQuestion) => {
  const n = q.scale || 5;
  return (q.display === "emoji" && EMOJI[n]) || Array.from({ length: n }, (_, i) => String(i + 1));
};

export function toQuestions(s: Survey): Question[] {
  return s.questions.filter((q) => q.type !== "link").map((q) => {
    if (q.type === "rating") {
      const labels = scaleLabels(q);
      return { question: q.question, open: false, multi: false,
               options: labels.map((label, i) => ({
                 label, hint: i === 0 ? q.lowerBoundLabel : i === labels.length - 1 ? q.upperBoundLabel : undefined })) };
    }
    if (q.type === "single_choice" || q.type === "multiple_choice")
      return { question: q.question, open: false, multi: q.type === "multiple_choice",
               options: (q.choices || []).map((label) => ({ label })) };
    return { question: q.question, open: true, multi: false, options: [] };
  });
}

const interaction = (s: Survey, action: string) =>
  s.current_iteration ? `$survey_${action}/${s.id}/${s.current_iteration}` : `$survey_${action}/${s.id}`;
const seenKey = (s: Survey) => s.current_iteration ? `seenSurvey_${s.id}_${s.current_iteration}` : `seenSurvey_${s.id}`;
const base = (s: Survey) => ({
  $survey_id: s.id, $survey_name: s.name,
  $survey_iteration: s.current_iteration, $survey_iteration_start_date: s.current_iteration_start_date,
});

/** The `survey sent` payload, shaped like posthog-js's own. */
export function sentProps(s: Survey, answers: (string[] | string)[]) {
  const asked = s.questions.filter((q) => q.type !== "link");
  const responses: Record<string, unknown> = {};
  const value = (q: SurveyQuestion, a: string[] | string | undefined) => {
    if (a == null || (Array.isArray(a) ? a.length === 0 : a === "")) return null;
    if (q.type === "rating") return scaleLabels(q).indexOf((a as string[])[0]) + 1;
    if (q.type === "single_choice") return (a as string[])[0];
    return a;
  };
  const questions = s.questions.map((q) => {
    const i = asked.indexOf(q);
    const v = i < 0 ? null : value(q, answers[i]);
    if (v != null && q.id) responses[`$survey_response_${q.id}`] = v;
    return { id: q.id, question: q.question, response: v };
  });
  return {
    ...base(s), ...responses,
    $survey_questions: questions,
    $survey_submission_id: crypto.randomUUID(),
    $survey_completed: true,
    $set: { [interaction(s, "responded")]: true },
  };
}

export function useSurvey(ready: boolean) {
  const state = useState<Survey | null>(null);
  const [, setSurvey] = state;
  useEffect(() => {
    const remote = surveysProvider();
    if (!ready || !remote) return;
    let alive = true;
    remote.on((list) => {
      if (!alive) return;
      const s = list.find((x) => x.type === "api" && x.questions?.some((q) => q.type !== "link"));
      if (s) setSurvey(s);
    });
    return () => { alive = false; };
  }, [ready, setSurvey]);
  return state;
}

export function SurveyStrip({ survey, onDone }: { survey: Survey; onDone: () => void }) {
  const qs = useMemo(() => toQuestions(survey), [survey]);
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState<(string[] | string)[]>(() => qs.map((q) => (q.open ? "" : [])));
  const [text, setText] = useState("");
  const toast = useToast();
  const remote = surveysProvider();
  useEffect(() => { remote?.event("survey shown", base(survey)); }, [survey, remote]);

  const q = qs[step];
  const last = step === qs.length - 1;
  const lang = langOf(q.question);
  const seen = () => { try { localStorage.setItem(seenKey(survey), "true"); } catch { /* private mode */ } };

  const commit = (value: string[] | string) => {
    const all = answers.map((a, i) => (i === step ? value : a));
    setAnswers(all);
    if (!last) { setStep(step + 1); setText(""); return; }
    remote?.event("survey sent", sentProps(survey, all));
    seen();
    toast.info(t("surveyThanks"));
    onDone();
  };
  const dismiss = () => {
    remote?.event("survey dismissed", { ...base(survey), $survey_partially_completed: step > 0,
                                          $set: { [interaction(survey, "dismissed")]: true } });
    seen();
    onDone();
  };
  const picked = answers[step] as string[];
  const toggle = (label: string) =>
    setAnswers((cur) => cur.map((a, i) => i !== step ? a
      : (a as string[]).includes(label) ? (a as string[]).filter((l) => l !== label) : [...(a as string[]), label]));

  const pill = "rounded-full border px-2.5 py-1 text-xs transition-colors cursor-pointer";
  return (
    <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.15 }} className="mb-2 px-1">
      <div dir={lang === "ar" ? "rtl" : "ltr"}
           className="flex flex-col gap-1.5 rounded-2xl border border-border bg-background px-3 py-2 sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-2">
        <div className="flex items-center gap-2 sm:contents">
          <span dir="auto" className="min-w-0 flex-1 text-xs text-muted-foreground sm:flex-none">{q.question}</span>
          <button onClick={dismiss} aria-label={tIn(lang, "dismiss")}
                  className="shrink-0 rounded-full p-1 text-muted-foreground/60 transition-colors hover:bg-secondary hover:text-foreground cursor-pointer sm:order-last sm:ms-auto">
            <Icon name="x" className="size-3" />
          </button>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {q.open ? (
            <input
              autoFocus value={text} dir="auto"
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && text.trim()) { e.preventDefault(); commit(text.trim()); } }}
              placeholder={tIn(lang, "typeAnswer")}
              className="h-7 min-w-40 flex-1 rounded-full border border-border bg-background px-3 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-foreground/30"
            />
          ) : q.options.map((o) => {
            const on = picked.includes(o.label);
            return (
              <button key={o.label} title={o.hint} dir="auto"
                      onClick={() => (q.multi ? toggle(o.label) : commit([o.label]))}
                      className={cn(pill, on ? "border-foreground bg-foreground text-background"
                                              : "border-border text-foreground hover:border-foreground/30 hover:bg-secondary/60")}>
                {o.label}
              </button>
            );
          })}
          {q.multi && (
            <button onClick={() => commit(picked)} disabled={!picked.length}
                    className={cn(pill, "border-foreground bg-foreground text-background disabled:opacity-40")}>
              {t("send")}
            </button>
          )}
        </div>
      </div>
    </motion.div>
  );
}
