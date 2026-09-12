import { createContext, memo, useContext, useState } from "react";
import { cn } from "../../lib/utils";
import { Icon } from "../icon";
import { t } from "../../lib/i18n";
import { track } from "../../lib/analytics";
import type { Part, Source } from "../../hooks/use-chat";
import { ConnectorIcon, type Connector } from "../connectors-dialog";
import { StepDot } from "./step-part";
import { Favicon, domainOf } from "./sources-part";

// The connectors the chat knows, for the logo on a call's step. Empty where nobody is signed in (a share).
export const ConnectorsContext = createContext<Connector[]>([]);

// A step that carries more than its line: a connector call's request and response, or a search's results.
export const isCall = (p: Part) => !!p.connector || p.result !== undefined || !!p.sources?.length;

const humanize = (s: string) => { const w = s.replace(/[_-]+/g, " ").trim(); return w.charAt(0).toUpperCase() + w.slice(1); };
const pretty = (args?: string) => { if (!args) return ""; try { return JSON.stringify(JSON.parse(args), null, 2); } catch { return args; } };

// A step like any other — the logo or glyph stands where the dot goes and shimmers while the call runs.
// What it did is behind the chevron: request and response for a connector, the pages for a search.
export const ToolCall = memo(function ToolCall({ p, live }: { p: Part; live?: boolean }) {
  const [open, setOpen] = useState(false);
  const c = useContext(ConnectorsContext).find((x) => x.name === p.connector);
  const sources = p.sources ?? [];
  const name = humanize(p.tool_name?.split(" · ").pop() ?? "");
  return (
    <div>
      <button type="button" onClick={() => setOpen((o) => !o)} className="flex w-full cursor-pointer items-center gap-2 py-1 text-start text-sm text-muted-foreground">
        {p.icon ? (
          <span className="relative flex size-5 shrink-0 items-center justify-center overflow-hidden rounded-xl border border-border/60 bg-white">
            <img src={p.icon} alt="" className="size-[68%] object-contain" />
            {live && <span className="logo-shimmer absolute inset-y-0 -inset-x-full" />}
          </span>
        ) : c ? (
          <span className="relative shrink-0 overflow-hidden rounded-xl">
            <ConnectorIcon c={c} className="size-5" />
            {live && <span className="logo-shimmer absolute inset-y-0 -inset-x-full" />}
          </span>
        ) : <StepDot live={live} toolName={p.tool_name} step={p.step} ok={p.ok} />}
        <span dir="auto" className="min-w-0 flex-1 truncate font-mono text-[13px]">
          {sources.length ? <span className="text-foreground">{p.step}</span> : (
            <>
              <span className="font-semibold text-foreground">{name}</span>
              {p.step && <><span className="text-foreground">(</span>{p.step}<span className="text-foreground">)</span></>}
            </>
          )}
        </span>
        {p.ok === false
          ? <span className="shrink-0 text-xs text-destructive">{t("failed")}</span>
          : sources.length > 0 && <span className="shrink-0 text-xs text-muted-foreground">{t("nResults").replace("{n}", String(sources.length))}</span>}
        <Icon name="chevron-down" className={cn("size-3 shrink-0 transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="mb-2 grid min-w-0 gap-2 ps-7">
          {sources.length ? <Results sources={sources} /> : (
            <>
              <Panel label={t("request")} body={pretty(p.args)} />
              <Panel label={t("response")} body={p.result ?? (live ? "…" : "")} />
            </>
          )}
        </div>
      )}
    </div>
  );
});

// What the search returned, in the order it returned them.
function Results({ sources }: { sources: Source[] }) {
  return (
    <div className="min-w-0 divide-y divide-border overflow-hidden rounded-xl border border-border">
      {sources.map((s, i) => (
        <a
          key={`${s.url}-${i}`}
          href={s.url}
          target="_blank"
          rel="noopener noreferrer"
          onClick={() => track("source_opened", { url: s.url, domain: domainOf(s.url), placement: "step" })}
          className="flex items-center gap-2.5 px-3 py-2 no-underline transition-colors hover:bg-secondary/50"
        >
          <Favicon url={s.url} className="size-4 shrink-0" />
          <span dir="auto" className="min-w-0 flex-1 truncate text-[13px] text-foreground">{s.title || domainOf(s.url)}</span>
          <span dir="ltr" className="hidden max-w-[40%] shrink-0 truncate text-xs text-muted-foreground sm:block">{domainOf(s.url)}</span>
        </a>
      ))}
    </div>
  );
}

function Panel({ label, body }: { label: string; body: string }) {
  return (
    <div className="min-w-0 rounded-xl border border-border bg-secondary/40">
      <div className="px-3 pt-2 text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <pre dir="ltr" className="max-h-64 overflow-auto whitespace-pre-wrap [overflow-wrap:anywhere] px-3 pb-2.5 pt-1 text-start font-mono text-[12px] leading-relaxed text-foreground">{body || "—"}</pre>
    </div>
  );
}
