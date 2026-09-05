// The agent asked for an account the user hasn't connected. Connect opens the
// provider in a new tab; the callback tab posts back and the card clears itself.
import { motion } from "framer-motion";
import { Icon } from "./icon";
import { t } from "../lib/i18n";

export function ConnectCard({ name, onConnect, onDismiss }: { name: string; onConnect: () => void; onDismiss: () => void }) {
  const label = name.charAt(0).toUpperCase() + name.slice(1);
  return (
    <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.15 }} className="mb-2 px-1">
      <div className="flex items-center gap-3 rounded-2xl border border-border bg-background px-3.5 py-2.5 shadow-sm">
        <Icon name="link" className="size-4 shrink-0 text-muted-foreground" />
        <p dir="auto" className="min-w-0 flex-1 text-sm leading-snug text-foreground">{t("connectNeeds").replace("{name}", label)}</p>
        <button onClick={onDismiss} className="shrink-0 rounded-full px-2.5 py-1 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground transition-colors cursor-pointer">
          {t("notNow")}
        </button>
        <button onClick={onConnect} className="shrink-0 rounded-full bg-foreground px-3.5 py-1.5 text-xs font-medium text-background transition hover:opacity-80 cursor-pointer">
          {t("connect")}
        </button>
      </div>
    </motion.div>
  );
}
