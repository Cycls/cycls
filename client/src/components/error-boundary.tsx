import { Component, type ReactNode } from "react";
import { t } from "../lib/i18n";
import { reference } from "../lib/errors";

// The crash screen names a reference, never the error: its text may be a library's, a vendor's name in it.
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null; ref?: string }> {
  state = { error: null as Error | null, ref: undefined as string | undefined };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch(error: Error) { this.setState({ ref: reference("client_crashed", error) }); }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="flex h-dvh items-center justify-center bg-background p-6 text-foreground">
        <div className="max-w-sm rounded-2xl border border-border bg-card p-6 text-center shadow-sm">
          <p className="text-sm font-medium">{t("somethingWrong")}</p>
          {this.state.ref && <p className="mt-2 font-mono text-[11px] text-muted-foreground">{t("reference")}: {this.state.ref}</p>}
          <button onClick={() => location.reload()} className="mt-4 cursor-pointer rounded-full bg-foreground px-4 py-2 text-sm font-medium text-background hover:opacity-80">{t("reload")}</button>
        </div>
      </div>
    );
  }
}
