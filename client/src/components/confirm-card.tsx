// The agent wants to run a gated tool. Approve sends the next turn with this call approved; Always allow
// first sets the tool to Allow on its connector's page; Cancel just clears the card.
import { motion } from "framer-motion";
import { Icon } from "./icon";
import { t } from "../lib/i18n";

export function ConfirmCard({ label, args, onApprove, onAlways, onDismiss }: { label: string; args: unknown; onApprove: () => void; onAlways: () => void; onDismiss: () => void }) {
  const preview = args && typeof args === "object"
    ? Object.entries(args as Record<string, unknown>).map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`).join(" · ")
    : "";
  return (
    <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.15 }} className="mb-2 px-1">
      <div className="rounded-2xl border border-border bg-background px-3.5 py-2.5 shadow-sm">
        <div className="flex items-center gap-3">
          <Icon name="link" className="size-4 shrink-0 text-muted-foreground" />
          <p dir="auto" className="min-w-0 flex-1 text-sm leading-snug text-foreground">{t("confirmNeeds").replace("{label}", label)}</p>
          <button onClick={onDismiss} className="shrink-0 cursor-pointer rounded-full px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground">{t("cancel")}</button>
          <button onClick={onAlways} title={t("alwaysAllowHint")} className="shrink-0 cursor-pointer rounded-full border border-border px-3 py-1 text-xs text-foreground transition-colors hover:bg-secondary">{t("alwaysAllow")}</button>
          <button onClick={onApprove} className="shrink-0 cursor-pointer rounded-full bg-foreground px-3.5 py-1.5 text-xs font-medium text-background transition hover:opacity-80">{t("approve")}</button>
        </div>
        {preview && <p dir="ltr" className="mt-1.5 truncate ps-7 font-mono text-[11px] text-muted-foreground">{preview}</p>}
      </div>
    </motion.div>
  );
}
