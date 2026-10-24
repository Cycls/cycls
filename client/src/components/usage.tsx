import { createContext, useContext } from "react";
import { Star } from "./cycls-star";
import { getLang, t } from "../lib/i18n";
import type { Part } from "../hooks/use-chat";

// An agent's limit, as it reports it with a reply (`{"type": "usage", "used", "limit", "per", "resets"}`): a line over
// the message box in its last fifth, and a note in place of the reply once nothing is left. Plans open from both.
export const UpgradeContext = createContext<{ upgrade?: () => void; agent?: string }>({});

const left = (u: Part) => Math.max(0, (u.limit ?? 0) - (u.used ?? 0));
export const nearLimit = (u?: Part | null): u is Part => !!u?.limit && left(u) <= Math.ceil(u.limit / 5);
export const usedUp = (u?: Part | null): u is Part => !!u?.limit && left(u) === 0;

// The day it comes back, in the reader's language; the Gregorian calendar, as the limit counts.
function day(iso?: string) {
  const d = iso ? new Date(`${iso.slice(0, 10)}T00:00:00`) : null;
  if (!d || isNaN(d.getTime())) return "";
  return d.toLocaleDateString(getLang() === "ar" ? "ar-u-ca-gregory" : "en-GB", { day: "numeric", month: "long" });
}

export function UsageLine({ usage }: { usage: Part }) {
  const { upgrade } = useContext(UpgradeContext);
  const n = left(usage), when = day(usage.resets);
  const words = n ? t("usageLeft").replace("{left}", String(n)).replace("{limit}", String(usage.limit)) : t("usageNoneLeft");
  return (
    <div className="mb-2 flex items-center gap-2.5 px-2 text-[13px] text-muted-foreground">
      <span className="h-1 w-14 shrink-0 overflow-hidden rounded-full bg-secondary">
        <span className="block h-full rounded-full bg-foreground" style={{ width: `${Math.min(100, ((usage.used ?? 0) / (usage.limit || 1)) * 100)}%` }} />
      </span>
      <span dir="auto" className="min-w-0 truncate">{words}{when && ` · ${t("usageBackOn").replace("{date}", when)}`}</span>
      {upgrade && (
        <button type="button" onClick={upgrade} className="ms-auto shrink-0 cursor-pointer font-medium text-foreground underline underline-offset-2">{t("subscribeShort")}</button>
      )}
    </div>
  );
}

// Thanks first: the person tried the agent, and the way on is one button.
export function UsageNote({ usage }: { usage: Part }) {
  const { upgrade, agent } = useContext(UpgradeContext);
  const when = day(usage.resets);
  const period = usage.per === "month" ? t("usageThisMonth") : usage.per === "quarter" ? t("usageThisQuarter") : t("usageYour");
  return (
    <div className="my-2 flex max-w-lg items-start gap-3 rounded-2xl border border-border p-4">
      <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-secondary text-muted-foreground"><Star hollow size={18} /></span>
      <div className="min-w-0">
        <p dir="auto" className="text-[15px] font-semibold leading-snug text-foreground">{agent ? t("usageThanks").replace("{agent}", agent) : t("usageThanksPlain")}</p>
        <p dir="auto" className="mt-0.5 text-[13px] leading-snug text-muted-foreground">
          {t("usageUsedUp").replace("{period}", period).replace("{limit}", String(usage.limit))}{when && ` ${t("usageComesBack").replace("{date}", when)}`}
        </p>
        {upgrade && (
          <button type="button" onClick={upgrade} className="mt-3 cursor-pointer rounded-full bg-foreground px-4 py-2 text-[13px] font-medium text-background transition hover:opacity-85">
            {t("subscribeKeepGoing")}
          </button>
        )}
      </div>
    </div>
  );
}
