// ExamplesShowcase: the "Example" app of each agent — prompts and what the agent made of
// them. It takes the content files as they are (apps/<agent>/example/examples.json):
// category as {en, ar} or an id, featured, did, sources, fictional, kind, and a `result`
// that is either ResultBlock[] (below) or the free-form object ContentResult renders.
// An app with kinds of its own passes renderResult. Shapes: kit/README.md.
import { useMemo, useState, type ReactNode } from "react";
import { BookOpenCheck, Copy, ExternalLink, Send, Sparkles, Star } from "lucide-react";
import { toast } from "sonner";
import { askAgent, copyText, features, useCycls, useViewState } from "../cycls";
import { pick, useLang, type L10n } from "../i18n";
import { useKitT } from "../strings";
import { Button } from "../ui/button";
import { Card } from "../ui/card";
import { StatusBadge, TONE_TEXT } from "./status-badge";
import { ResponsiveSheet } from "./responsive-sheet";
import { ContentResult, useText } from "./content-result";
import { DocMock, Markdownish, MiniChart, MiniTable, SafeImage, type ChartDatum } from "./rich";
import { cn } from "../lib/utils";

export type ResultBlock =
  | { type: "text"; md: L10n }
  | { type: "table"; columns: L10n[]; rows: (string | number | L10n)[][]; caption?: L10n }
  | { type: "chart"; kind: "bar" | "line" | "donut"; data: ChartDatum[]; unit?: L10n; title?: L10n }
  | { type: "image"; src: string; alt: L10n }
  | { type: "doc"; kind: L10n; title: L10n; meta?: { k: L10n; v: L10n }[]; body: L10n }
  | { type: "kpis"; items: { label: L10n; value: L10n; hint?: L10n; tone?: "success" | "warning" | "danger" | "info" }[] };

export interface ExampleCategory { id: string; label: L10n; icon?: ReactNode }
export interface Example {
  id: string;
  /** a category id (see `categories`) or a label {en, ar} — categories are then derived */
  category: string | L10n;
  title: L10n;
  /** what the person would type — "Try this prompt" (cut to 1000 chars for cycls.ask) */
  prompt: L10n;
  summary?: L10n;
  featured?: boolean;
  kind?: string;
  /** ResultBlock[] or the content files' free-form result object */
  result: ResultBlock[] | Record<string, unknown> | L10n;
  /** "what the agent did", shown in the detail sheet */
  did?: L10n;
  /** URLs, or code references ("prompt.py:58") — shown as text, URLs as links */
  sources?: (string | { title?: L10n; url: string })[];
  fictional?: boolean | L10n;
  tags?: L10n[];
}

const isBlocks = (r: unknown): r is ResultBlock[] => Array.isArray(r) && r.every((b) => b && typeof b === "object" && "type" in b);

export function ResultView({ block, compact = false }: { block: ResultBlock; compact?: boolean }) {
  const { lang } = useLang();
  switch (block.type) {
    case "text": return <Markdownish text={pick(block.md, lang)} className={compact ? "line-clamp-6 text-xs" : undefined} />;
    case "table": return <MiniTable columns={block.columns} rows={compact ? block.rows.slice(0, 4) : block.rows} caption={compact ? undefined : block.caption} />;
    case "chart": return <MiniChart kind={block.kind} data={block.data} unit={block.unit} title={block.title} />;
    case "image": return <SafeImage src={block.src} alt={pick(block.alt, lang)} className={compact ? "max-h-40" : undefined} />;
    case "doc": return <DocMock kind={pick(block.kind, lang)} title={block.title} meta={compact ? block.meta?.slice(0, 2) : block.meta} body={compact ? { en: firstLines(pick(block.body, "en")), ar: firstLines(pick(block.body, "ar")) } : block.body} />;
    case "kpis": return (
      <div className="grid grid-cols-2 gap-2">
        {block.items.map((k, i) => (
          <div key={i} className="min-w-0 rounded-lg border bg-card p-3">
            <div className="truncate text-xs text-muted-foreground">{pick(k.label, lang)}</div>
            <div className={cn("num mt-0.5 truncate text-lg font-semibold", k.tone && TONE_TEXT[k.tone])}>{pick(k.value, lang)}</div>
            {k.hint && <div className="truncate text-[11px] text-muted-foreground">{pick(k.hint, lang)}</div>}
          </div>
        ))}
      </div>
    );
  }
}
const firstLines = (s: string) => s.split("\n").slice(0, 4).join("\n");

function DefaultResult({ example, compact }: { example: Example; compact: boolean }) {
  if (isBlocks(example.result)) {
    const blocks = compact ? example.result.slice(0, 1) : example.result;
    return <div className="space-y-3">{blocks.map((b, i) => <ResultView key={i} block={b} compact={compact} />)}</div>;
  }
  return <ContentResult result={example.result} compact={compact} />;
}

/** Puts the prompt in the chat composer when the host can (never sends), else copies it,
 *  else shows it selectable. */
export function TryPrompt({ text, className }: { text: string; className?: string }) {
  const t = useKitT();
  const { mode } = useCycls();
  const [manual, setManual] = useState(false);
  const canAsk = mode === "live" && features.ask;
  return (
    <div className={cn("w-full space-y-2 sm:w-auto", className)}>
      <Button className="w-full sm:w-auto" onClick={async () => {
        if (canAsk && (await askAgent(text))) { toast.success(t("askedAgent")); return; }
        if (copyText(text)) { toast.success(t("copied")); return; }
        setManual(true);
        toast.info(t("copyFailed"));
      }}>
        {canAsk ? <Send className="rtl:-scale-x-100" /> : <Copy />}{canAsk ? t("tryPrompt") : t("copyPrompt")}
      </Button>
      {manual && <textarea readOnly value={text} rows={4} onFocus={(e) => e.currentTarget.select()} autoFocus
        className="w-full rounded-lg border bg-muted p-2 text-sm" aria-label={t("prompt")} />}
    </div>
  );
}

const catId = (c: string | L10n) => (typeof c === "string" ? c : c.en || c.ar);

export function ExamplesShowcase({ title, intro, categories, examples, renderResult, stateKey = "showcase", sheetClassName }: {
  /** widens the detail sheet on desktop, e.g. "sm:max-w-4xl" (default sm:max-w-xl) */
  sheetClassName?: string;
  /** namespaces the remembered category/open card when a page has two showcases */
  stateKey?: string;
  title?: ReactNode; intro?: ReactNode; categories?: ExampleCategory[]; examples: Example[];
  /** render a result yourself (return undefined to fall back to the default renderer) */
  renderResult?: (example: Example, compact: boolean) => ReactNode | undefined;
}) {
  const { lang } = useLang();
  const t = useKitT();
  const { text } = useText();
  const cats = useMemo<ExampleCategory[]>(() => {
    if (categories?.length) return categories;
    const seen = new Map<string, ExampleCategory>();
    for (const e of examples) { const id = catId(e.category); if (!seen.has(id)) seen.set(id, { id, label: typeof e.category === "string" ? e.category : e.category }); }
    return [...seen.values()];
  }, [categories, examples]);
  const [cat, setCat] = useViewState<string>(`kit:${stateKey}-cat`, "all");
  const [openId, setOpenId] = useViewState<string | null>(`kit:${stateKey}-open`, null);
  const shown = useMemo(() => {
    const list = cat === "all" ? examples : examples.filter((e) => catId(e.category) === cat);
    return [...list].sort((a, b) => Number(!!b.featured) - Number(!!a.featured));
  }, [cat, examples]);
  const open = examples.find((e) => e.id === openId) ?? null;
  const result = (e: Example, compact: boolean) => renderResult?.(e, compact) ?? <DefaultResult example={e} compact={compact} />;
  const fictional = (e: Example) => e.fictional ?? (e.result && typeof e.result === "object" && !Array.isArray(e.result) ? (e.result as Record<string, unknown>).fictional as boolean | L10n | undefined : undefined);
  const catLabel = (e: Example) => pick(cats.find((c) => c.id === catId(e.category))?.label, lang);

  return (
    <div className="mx-auto max-w-7xl space-y-4 px-3 py-4 sm:px-4">
      {(title || intro) && (
        <div className="space-y-1">
          {title && <h2 className="flex items-center gap-2 text-lg font-semibold"><Sparkles className="size-5 text-primary" />{title}</h2>}
          {intro && <p className="text-sm text-muted-foreground">{intro}</p>}
        </div>
      )}
      <div role="tablist" aria-label={t("examples")} className="relative -mx-3 flex gap-2 overflow-x-auto px-3 pb-1 contain-inline-size sm:mx-0 sm:flex-wrap sm:px-0">
        {[{ id: "all", label: t("all") as L10n, icon: undefined as ReactNode }, ...cats].map((c) => (
          <button key={c.id} type="button" role="tab" aria-selected={cat === c.id} onClick={() => setCat(c.id)}
            className={cn("inline-flex h-10 shrink-0 items-center gap-1.5 rounded-full border px-4 text-sm [&_svg]:size-4",
              cat === c.id ? "border-primary bg-primary-soft text-primary" : "bg-card text-muted-foreground hover:text-foreground")}>
            {c.icon}{pick(c.label, lang)}
          </button>
        ))}
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {shown.map((e) => (
          <Card key={e.id} className="min-w-0 gap-0 overflow-hidden py-0">
            <button type="button" onClick={() => setOpenId(e.id)} className="flex min-w-0 flex-1 flex-col gap-3 p-4 text-start hover:bg-muted/50">
              <div className="min-w-0 space-y-1">
                <div className="flex flex-wrap items-center gap-1.5">
                  <StatusBadge tone="primary">{catLabel(e)}</StatusBadge>
                  {e.featured && <Star aria-hidden className="size-3.5 fill-current text-warning" />}
                  {fictional(e) ? <StatusBadge tone="neutral">{t("fictional")}</StatusBadge> : null}
                </div>
                <h3 className="break-words text-sm font-semibold">{pick(e.title, lang)}</h3>
                {e.summary && <p className="text-xs text-muted-foreground">{pick(e.summary, lang)}</p>}
              </div>
              {/* padding on the box, clamp on the inner span: a clamped box with padding shows ~8 px of a 4th line */}
              <p className="rounded-lg bg-muted px-3 py-2 text-xs text-muted-foreground"><span className="line-clamp-3" data-clamp="">“{pick(e.prompt, lang)}”</span></p>
              {/* cycls-default-apps: fade the clipped preview instead of cutting it mid-line */}
              <div className="pointer-events-none max-h-56 min-w-0 overflow-hidden [mask-image:linear-gradient(to_bottom,black_75%,transparent)]" aria-hidden>{result(e, true)}</div>
            </button>
          </Card>
        ))}
      </div>
      <ResponsiveSheet className={sheetClassName} open={!!open} onOpenChange={(o) => !o && setOpenId(null)} title={open ? pick(open.title, lang) : ""}
        footer={open ? <TryPrompt text={pick(open.prompt, lang)} /> : undefined}>
        {open && (
          <div className="space-y-4">
            {typeof fictional(open) === "object" && <p className="rounded-lg bg-muted px-3 py-2 text-xs text-muted-foreground">{text(fictional(open))}</p>}
            <section className="space-y-1.5">
              <h4 className="text-xs font-medium text-muted-foreground">{t("prompt")}</h4>
              <p className="select-text rounded-lg bg-muted px-3 py-2 text-sm">{pick(open.prompt, lang)}</p>
            </section>
            <section className="space-y-2">
              <h4 className="text-xs font-medium text-muted-foreground">{t("result")}</h4>
              {result(open, false)}
            </section>
            {open.did && (
              <section className="space-y-1.5">
                <h4 className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground"><BookOpenCheck className="size-4" />{t("whatAgentDid")}</h4>
                <Markdownish text={pick(open.did, lang)} />
              </section>
            )}
            {open.sources && open.sources.length > 0 && (
              <section className="space-y-1.5">
                <h4 className="text-xs font-medium text-muted-foreground">{t("sources")}</h4>
                <ul className="space-y-1 text-xs">
                  {open.sources.map((s, i) => {
                    const url = typeof s === "string" ? s : s.url;
                    const label = typeof s === "string" ? s : pick(s.title, lang) || s.url;
                    return (
                      <li key={i} dir="ltr" className="break-all text-start">
                        {/^https?:\/\//.test(url)
                          ? <a href={url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-primary underline-offset-2 hover:underline">{label}<ExternalLink className="size-3" /></a>
                          : <code className="text-muted-foreground">{label}</code>}
                      </li>
                    );
                  })}
                </ul>
              </section>
            )}
          </div>
        )}
      </ResponsiveSheet>
    </div>
  );
}
