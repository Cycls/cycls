import { useState, useEffect } from "react";
import { t } from "../lib/i18n";
import { Popover } from "./popover";
import { Icon, Spinner } from "./icon";

// Mounted only while open (parent conditionally renders it), so the form
// state resets to fresh each time the dialog is opened.
export function ShareDialog({ onClose, mode = "chat", subtitle = "", org, onShare, onManageShares }: {
  onClose: () => void;
  mode?: "chat" | "file";
  subtitle?: string;
  org?: { id: string; name: string } | null;
  onShare: (audience: string) => Promise<string>;
  onManageShares?: () => void;
}) {
  const [audience, setAudience] = useState("public");
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <Popover open onClose={onClose} className="right-2 top-12 mt-2 w-80 max-w-[calc(100vw-1rem)] rounded-lg border border-border bg-background shadow-lg overflow-hidden">
      <div className="px-4 pt-4 pb-3">
        <div className="flex items-center gap-2 mb-1">
          <Icon name="link" className="w-4 h-4 text-foreground shrink-0" />
          <h3 className="flex-1 text-sm font-medium text-foreground">
            {mode === "file" ? t("shareFile") : t("shareConversation")}
          </h3>
          <button onClick={onClose} aria-label="Close" className="shrink-0 -mr-1 -mt-1 flex size-7 items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors cursor-pointer">
            <Icon name="x" className="w-4 h-4" />
          </button>
        </div>
        {mode === "file" && subtitle && (
          <p className="mb-3 truncate text-[11px] text-muted-foreground" dir="auto">{subtitle}</p>
        )}
        <div className="flex gap-1.5 mt-3">
          {(["public", ...(org ? [`org:${org.id}`] : [])] as string[]).map((aud) => (
            <button
              key={aud}
              onClick={() => setAudience(aud)}
              className={`text-[11px] px-2.5 py-1 rounded-full transition-colors cursor-pointer ${audience === aud ? "bg-secondary text-foreground" : "text-muted-foreground hover:bg-secondary/50"}`}
            >
              {aud.startsWith("org:") ? `${t("anyoneInOrg")} ${org!.name}` : t("anyoneWithLink")}
            </button>
          ))}
        </div>
      </div>

      <div className="border-t border-border px-4 py-3">
        {loading ? (
          <div className="flex items-center justify-center py-2">
            <Spinner className="w-4 h-4 text-muted-foreground" />
            <span className="ml-2 text-xs text-muted-foreground">{t("creatingLink")}</span>
          </div>
        ) : url ? (
          <div className="flex items-center gap-2">
            <input
              type="text"
              readOnly
              value={url}
              onFocus={(e) => e.target.select()}
              className="flex-1 min-w-0 rounded-md border border-border bg-secondary/50 px-2.5 py-1.5 text-xs text-foreground select-all focus:outline-none"
            />
            <button
              onClick={() => { navigator.clipboard.writeText(url); setCopied(true); setTimeout(() => setCopied(false), 2000); }}
              className="shrink-0 text-muted-foreground hover:text-foreground transition-colors cursor-pointer p-1.5"
              aria-label="Copy"
            >
              <Icon name={copied ? "check" : "copy"} className="w-3.5 h-3.5" />
            </button>
          </div>
        ) : (
          <>
            <button
              onClick={() => {
                setLoading(true);
                setFailed(false);
                onShare(audience).then((u) => { setUrl(u); setLoading(false); }).catch(() => { setFailed(true); setLoading(false); });
              }}
              className="w-full rounded-md border border-border bg-secondary hover:bg-secondary/80 text-foreground py-2 text-xs font-medium transition-colors cursor-pointer"
            >
              {t("createLink")}
            </button>
            {failed && <p className="mt-2 text-center text-[11px] text-red-500">{t("shareFailed")}</p>}
          </>
        )}
      </div>

      {onManageShares && (
        <div className="border-t border-border">
          <button
            onClick={onManageShares}
            className="flex w-full items-center justify-between px-4 py-2.5 text-xs text-muted-foreground hover:text-foreground hover:bg-secondary/50 transition-colors cursor-pointer"
          >
            {t("manageShares")}
            <Icon name="chevron-right" className="w-3.5 h-3.5 rtl:rotate-180" />
          </button>
        </div>
      )}
    </Popover>
  );
}
