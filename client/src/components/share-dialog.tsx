import { useEffect, useState } from "react";
import { t } from "../lib/i18n";
import { Popover } from "./popover";
import { Icon, Spinner } from "./icon";

// A link already made for something ("chat/<id>" / "file/<path>"), and taking it back.
export interface ShareLink { token: string; url: string; audience?: string }
export interface ShareLinks {
  find: (path: string) => Promise<ShareLink[]>;
  revoke: (token: string) => Promise<void>;
}

const absolute = (url: string) => (/^https?:/.test(url) ? url : `${window.location.origin}${url}`);

// Mounted only while open (parent conditionally renders it), so the form
// state resets to fresh each time the dialog is opened.
//
// With `path` + `links` it first looks for the links this thing already has: one made
// earlier is shown (copy it, or remove it) instead of offering to make another.
export function ShareDialog({ onClose, mode = "chat", subtitle = "", org, onShare, onManageShares, path, links }: {
  onClose: () => void;
  mode?: "chat" | "file";
  subtitle?: string;
  org?: { id: string; name: string } | null;
  onShare: (audience: string) => Promise<string>;
  onManageShares?: () => void;
  path?: string;
  links?: ShareLinks;
}) {
  const [audience, setAudience] = useState("public");
  const [existing, setExisting] = useState<ShareLink[] | null>(links && path ? null : []);   // null: looking
  const [made, setMade] = useState<Record<string, string>>({});   // audience → the link just created
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!links || !path) return;
    let live = true;
    links.find(path).then((found) => { if (live) setExisting(found); }).catch(() => { if (live) setExisting([]); });
    return () => { live = false; };
  }, [links, path]);

  const link = existing?.find((s) => (s.audience ?? "public") === audience) ?? null;
  const url = link ? absolute(link.url) : made[audience] ?? null;

  const create = () => {
    setLoading(true);
    setFailed(false);
    onShare(audience)
      .then((u) => {
        setMade((m) => ({ ...m, [audience]: u }));
        // Pick up its token, so the link can be removed from here too.
        if (links && path) links.find(path).then(setExisting).catch(() => {});
      })
      .catch(() => setFailed(true))
      .finally(() => setLoading(false));
  };
  const remove = () => {
    if (!links || !link) return;
    setLoading(true);
    links.revoke(link.token)
      .then(() => {
        setExisting((found) => (found ?? []).filter((s) => s.token !== link.token));
        setMade((m) => Object.fromEntries(Object.entries(m).filter(([aud]) => aud !== audience)));
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  };

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
              onClick={() => { setAudience(aud); setCopied(false); setFailed(false); }}
              className={`text-[11px] px-2.5 py-1 rounded-full transition-colors cursor-pointer ${audience === aud ? "bg-secondary text-foreground" : "text-muted-foreground hover:bg-secondary/50"}`}
            >
              {aud.startsWith("org:") ? `${t("anyoneInOrg")} ${org!.name}` : t("anyoneWithLink")}
            </button>
          ))}
        </div>
      </div>

      <div className="border-t border-border px-4 py-3">
        {loading || existing === null ? (
          <div className="flex items-center justify-center py-2">
            <Spinner className="w-4 h-4 text-muted-foreground" />
            {loading && !link && <span className="ml-2 text-xs text-muted-foreground">{t("creatingLink")}</span>}
          </div>
        ) : url ? (
          <>
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
            {link && links && (
              <button onClick={remove} className="mt-2 text-[11px] text-muted-foreground hover:text-red-500 transition-colors cursor-pointer">
                {t("removeLink")}
              </button>
            )}
          </>
        ) : (
          <>
            <button
              onClick={create}
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
