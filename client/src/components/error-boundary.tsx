import { Component, type ReactNode } from "react";
import { t } from "../lib/i18n";
import { track } from "../lib/analytics";

export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch(error: Error) { track("client_crashed", { message: String(error?.message || error).slice(0, 200) }); }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="flex h-dvh items-center justify-center bg-background p-6 text-foreground">
        <div className="max-w-sm rounded-2xl border border-border bg-card p-6 text-center shadow-sm">
          <p className="text-sm font-medium">{t("somethingWrong")}</p>
          <p dir="ltr" className="mt-2 truncate font-mono text-[11px] text-muted-foreground">{this.state.error.message}</p>
          <button onClick={() => location.reload()} className="mt-4 cursor-pointer rounded-full bg-foreground px-4 py-2 text-sm font-medium text-background hover:opacity-80">{t("reload")}</button>
        </div>
      </div>
    );
  }
}
