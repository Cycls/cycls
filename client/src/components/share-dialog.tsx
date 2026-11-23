// Sharing a chat or a file: the card people will see, who can open it, and the ways to send it. Choosing who makes the
// link at once, changing it keeps the same link, and "Only you" takes it back. Under the button on a computer, a sheet
// from the bottom on a phone. Mounted only while open, so it starts fresh each time.
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { t, getLang } from "../lib/i18n";
import { cn } from "../lib/utils";
import { useEscape } from "../hooks/use-escape";
import { Icon, Spinner, type IconName } from "./icon";

// Existing links to "chat/<id>" or "file/<path>": found, taken back, and who can open one changed.
export interface ShareLink { token: string; url: string; audience?: string }
export interface ShareLinks {
  find: (path: string) => Promise<ShareLink[]>;
  revoke: (token: string) => Promise<void>;
  change?: (token: string, audience: string) => Promise<void>;
}

const absolute = (url: string) => (/^https?:/.test(url) ? url : `${window.location.origin}${url}`);

const WHATSAPP = "M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413Z";

export function ShareDialog({ onClose, mode = "chat", subtitle = "", org, onShare, path, links }: {
  onClose: () => void;
  mode?: "chat" | "file";
  subtitle?: string;   // the chat's title or the file's name
  org?: { id: string; name: string } | null;
  onShare: (audience: string) => Promise<string>;
  path?: string;
  links?: ShareLinks;
}) {
  const [found, setFound] = useState<ShareLink[] | null>(links && path ? null : []);   // null: looking
  const [made, setMade] = useState<ShareLink | null>(null);   // one made where links can't be looked up
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);
  useEscape(onClose, true);

  useEffect(() => {
    if (!links || !path) return;
    let live = true;
    links.find(path).then((f) => { if (live) setFound(f); }).catch(() => { if (live) setFound([]); });
    return () => { live = false; };
  }, [links, path]);

  const link = found?.[0] ?? made;
  const now = link ? link.audience ?? "public" : "none";
  const url = link ? absolute(link.url) : "";
  const waiting = found === null || busy;
  const choose = async (audience: string) => {
    if (audience === now || waiting) return;
    setBusy(true);
    setFailed(false);
    setCopied(false);
    try {
      if (audience === "none") {
        await Promise.all((found ?? []).map((s) => links!.revoke(s.token)));
        setFound([]);
        setMade(null);
      } else if (link?.token && links?.change) {
        await links.change(link.token, audience);
        setFound((f) => f?.map((s) => (s.token === link.token ? { ...s, audience } : s)) ?? f);
      } else {
        const u = await onShare(audience);
        if (links && path) setFound(await links.find(path));
        else setMade({ token: "", url: u, audience });
      }
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };
  const copy = () => {
    navigator.clipboard?.writeText(url).then(() => { setCopied(true); setTimeout(() => setCopied(false), 2000); }, () => {});
  };

  const choices: { key: string; icon: IconName; short: string; label: string }[] = [
    { key: "none", icon: "lock", short: t("onlyYou"), label: t("onlyYou") },
    ...(org ? [{ key: `org:${org.id}`, icon: "org" as IconName, short: org.name, label: `${t("anyoneInOrg")} ${org.name}` }] : []),
    { key: "public", icon: "globe", short: t("anyone"), label: t("anyoneWithLink") },
  ];
  const current = choices.find((c) => c.key === now) ?? choices[0];
  const name = subtitle || t(mode === "file" ? "shareFile" : "shareConversation");
  const target = "flex size-10 shrink-0 cursor-pointer items-center justify-center rounded-xl bg-secondary text-foreground transition-colors hover:bg-secondary/70";

  return createPortal(
    <div dir={getLang() === "ar" ? "rtl" : "ltr"}>
      <div className="fixed inset-0 z-[70] bg-black/40 sm:bg-transparent" onClick={onClose} />
      <div role="dialog" aria-label={t(mode === "file" ? "shareFile" : "shareConversation")}
           className="fixed inset-x-0 bottom-0 z-[80] rounded-t-2xl border border-border bg-background p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] shadow-xl sm:inset-x-auto sm:bottom-auto sm:right-2 sm:top-13.5 sm:mt-2 sm:w-[21rem] sm:rounded-2xl sm:pb-3">
        <div className="flex aspect-[40/21] items-center justify-center overflow-hidden rounded-xl bg-secondary text-muted-foreground">
          {link && !busy
            ? <img src={url.replace("/shared/", "/share/").replace(/(\?|$)/, "/card.png$1")} alt="" className="size-full object-cover" />
            : waiting ? <Spinner className="size-5" /> : <Icon name="lock" className="size-6" strokeWidth={1.5} />}
        </div>
        <p className="truncate px-1 pt-3 text-sm font-medium text-foreground"><bdi>{name}</bdi></p>
        <div role="radiogroup" aria-label={t("whoCanOpen")} className="mt-2.5 grid auto-cols-fr grid-flow-col gap-0.5 rounded-xl bg-secondary p-1">
          {choices.map((c) => (
            <button key={c.key} role="radio" aria-checked={now === c.key} disabled={waiting} onClick={() => void choose(c.key)}
                    className={cn("flex min-w-0 cursor-pointer items-center justify-center gap-1.5 rounded-lg px-2 py-1.5 text-xs transition disabled:cursor-default",
                                  now === c.key ? "bg-background font-medium text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}>
              <Icon name={c.icon} className="size-3.5 shrink-0" /><span className="truncate">{c.short}</span>
            </button>
          ))}
        </div>
        <p className="min-h-5 px-1 pt-2 text-xs leading-5 text-muted-foreground">
          {found === null ? "" : now === "none" ? t("onlyYouCan") : `${current.label} ${t(mode === "file" ? "canOpenFile" : "canOpenChat")}`}
        </p>
        {link && (
          <div className="mt-3 flex gap-2">
            <button onClick={copy} className="flex h-10 flex-1 cursor-pointer items-center justify-center gap-2 rounded-xl bg-foreground text-sm font-medium text-background transition hover:opacity-85">
              <Icon name={copied ? "check" : "copy"} className="size-4" />{t(copied ? "copied" : "copyLink")}
            </button>
            <a href={`https://wa.me/?text=${encodeURIComponent(`${name}\n${url}`)}`} target="_blank" rel="noreferrer" aria-label="WhatsApp" title="WhatsApp" className={target}>
              <svg viewBox="0 0 24 24" className="size-[18px]" fill="#25D366"><path d={WHATSAPP} /></svg>
            </a>
            <a href={`mailto:?subject=${encodeURIComponent(name)}&body=${encodeURIComponent(url)}`} aria-label={t("email")} title={t("email")} className={target}>
              <Icon name="mail" className="size-[18px]" />
            </a>
            {"share" in navigator && (
              <button onClick={() => navigator.share({ title: name, url }).catch(() => {})} aria-label={t("more")} title={t("more")} className={target}>
                <Icon name="upload" className="size-[18px]" />
              </button>
            )}
          </div>
        )}
        {failed && <p className="px-1 pt-2 text-xs text-red-500">{t("shareFailed")}</p>}
      </div>
    </div>,
    document.body,
  );
}
