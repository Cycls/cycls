import { Component, useEffect, useRef, type ErrorInfo, type ReactNode } from "react";
import { Direction } from "radix-ui";
import { Info, RotateCw, TriangleAlert } from "lucide-react";
import { Toaster } from "../ui/sonner";
import { TooltipProvider } from "../ui/tooltip";
import { CyclsProvider, getView, REFRESH_SCROLL_KEY, setDemoToastText, setView, useCycls } from "../cycls";
import { LangProvider, useLang } from "../i18n";
import { useKitT } from "../strings";
import { ThemeProvider } from "./theme";

/** Every app's root: mode detection, language + radix direction, theme (.dark), toasts,
 *  tooltips, the demo banner and an error boundary. `children` renders once the mode is
 *  known (≤ 2.5 s when opened outside Cycls). */
export function AppShell({ children }: { children: ReactNode }) {
  return (
    <ErrorBoundary>
      <CyclsProvider>
        <LangProvider>
          <ThemeProvider>
            <Chrome>{children}</Chrome>
          </ThemeProvider>
        </LangProvider>
      </CyclsProvider>
    </ErrorBoundary>
  );
}

function Chrome({ children }: { children: ReactNode }) {
  const { pending } = useCycls();
  const { dir } = useLang();
  const t = useKitT();
  useEffect(() => { setDemoToastText(t("demoToast")); }, [t]);
  return (
    // Radix reads direction from this provider, not from <html dir>: without it Select,
    // DropdownMenu, Tabs arrow keys and ScrollArea behave LTR in Arabic.
    <Direction.Provider dir={dir}>
      <TooltipProvider delayDuration={300}>
        {pending ? (
          <div role="status" aria-busy="true" className="flex min-h-dvh items-center justify-center">
            <span className="size-5 animate-spin rounded-full border-2 border-border border-t-primary" aria-hidden />
            <span className="sr-only">{t("loading")}</span>
          </div>
        ) : (
          <>
            <DemoBanner />
            <ErrorBoundary>{children}</ErrorBoundary>
            <RestoreScroll />
          </>
        )}
        {/* Toasts are click-through: they sit over the Toolbar at the top, and a hovered toast
            never times out (sonner pauses on hover), so a pointer over one would block the title
            and the actions behind it. No kit or app toast has an action button. */}
        <Toaster dir={dir} position="top-center" containerAriaLabel={t("notifications")} toastOptions={{ style: { pointerEvents: "none" } }} />
      </TooltipProvider>
    </Direction.Provider>
  );
}

export function DemoBanner() {
  const { demo, reason } = useCycls();
  const t = useKitT();
  if (!demo) return null;
  const why = reason === "no-shim" || reason === "no-ready" ? t("demoNoShim") : reason === "no-answer" ? t("demoNoAnswer") : t("demoGallery");
  return (
    <div role="note" data-kit-demo={reason} className="flex items-center gap-2 border-b bg-info-soft px-3 py-1.5 text-xs text-info">
      <Info aria-hidden className="size-4 shrink-0" />
      <span className="min-w-0"><strong className="font-semibold">{t("demoBanner")}</strong> · {why}</span>
    </div>
  );
}

/** After the turn_end reload, put the page back where it was. */
function RestoreScroll() {
  const done = useRef(false);
  useEffect(() => {
    if (done.current) return;
    done.current = true;
    const s = getView<{ x: number; y: number } | null>(REFRESH_SCROLL_KEY, null);
    if (!s) return;
    setView(REFRESH_SCROLL_KEY, null);
    setTimeout(() => window.scrollTo(s.x, s.y), 150);   // after the first data render
  }, []);
  return null;
}

// ---- error boundary -------------------------------------------------------------------

interface EBState { error: Error | null }
export class ErrorBoundary extends Component<{ children: ReactNode }, EBState> {
  state: EBState = { error: null };
  static getDerivedStateFromError(error: Error): EBState { return { error }; }
  componentDidCatch(error: Error, info: ErrorInfo) {
    // A render error caught here is not "uncaught", so the shim never hears of it.
    // Re-dispatching it as an ErrorEvent lets the shim's listener post cycls:loaderror,
    // and the host shows its crash bar with this message.
    const where = info.componentStack?.split("\n").map((l) => l.trim()).filter(Boolean)[0];
    try { window.dispatchEvent(new ErrorEvent("error", { message: error.message + (where ? ` (${where})` : "") })); } catch { /* ignore */ }
  }
  render() {
    if (!this.state.error) return this.props.children;
    return <Crash error={this.state.error} onRetry={() => this.setState({ error: null })} />;
  }
}

function Crash({ error, onRetry }: { error: Error; onRetry: () => void }) {
  // May render outside the providers, so it reads the language from <html>.
  const ar = document.documentElement.lang === "ar";
  return (
    <div role="alert" className="mx-auto flex max-w-md flex-col items-center gap-3 px-6 py-16 text-center">
      <div className="grid size-12 place-items-center rounded-2xl bg-destructive-soft text-destructive"><TriangleAlert className="size-6" /></div>
      <h2 className="text-lg font-semibold">{ar ? "حدث خطأ" : "Something went wrong"}</h2>
      <p className="text-sm text-muted-foreground">{ar ? "توقف هذا الجزء من التطبيق بسبب خطأ. بياناتك المحفوظة سليمة." : "This part of the app hit an error. Your saved data is safe."}</p>
      <pre dir="ltr" className="max-w-full overflow-x-auto whitespace-pre-wrap break-words rounded-lg bg-muted px-3 py-2 text-start text-xs text-muted-foreground">{error.message}</pre>
      <button type="button" onClick={onRetry} className="inline-flex h-10 items-center gap-2 rounded-lg border px-4 text-sm font-medium hover:bg-accent">
        <RotateCw className="size-4" />{ar ? "إعادة المحاولة" : "Try again"}
      </button>
    </div>
  );
}
