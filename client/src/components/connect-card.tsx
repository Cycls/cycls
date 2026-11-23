// The connectors the agent needs, in its message: the ones that fit, each with its logo, its line and Connect, one
// already connected with ✓, and one Not now under them. It stays with the chat, so a run that stopped on it still
// shows it when opened later; once one is connected, the agent carries on by itself.
import { createContext, useContext } from "react";
import { ConnectorIcon, connectorLabel, L, type Connector } from "./connectors-dialog";
import { Icon } from "./icon";
import { uiDir } from "./routine-card";
import { t } from "../lib/i18n";

export const ConnectContext = createContext<{ connectors?: Connector[]; connect: (name: string) => void; skip: (names: string[]) => void }>(
  { connect: () => {}, skip: () => {} });

export function QuickConnect({ card }: { card: { connector?: string; connectors?: string[] } }) {
  const { connectors, connect, skip } = useContext(ConnectContext);
  const names = card.connectors?.length ? card.connectors : card.connector ? [card.connector] : [];
  const rows = names.map((n) => connectors?.find((c) => c.name === n) ?? ({ name: n } as Connector));
  if (!rows.length) return null;
  return (
    <div dir={uiDir()} className="my-3 w-full rounded-2xl border border-border bg-background p-1.5">
      {rows.map((c) => (
        <div key={c.name} className="flex items-center gap-3 rounded-xl px-2.5 py-2">
          <ConnectorIcon c={c} className="size-8" />
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-medium text-foreground">{connectorLabel(c)}</span>
            {L(c.description) && <span dir="auto" className="block truncate text-xs text-muted-foreground">{L(c.description)}</span>}
          </span>
          {c.connected
            ? <span className="flex shrink-0 items-center gap-1 text-xs text-muted-foreground"><Icon name="check" className="size-3.5" />{t("connectedLabel")}</span>
            : <button onClick={() => connect(c.name)}
                      className="shrink-0 cursor-pointer rounded-full bg-foreground px-3.5 py-1.5 text-xs font-medium text-background transition hover:opacity-80">
                {t("connectShort")}
              </button>}
        </div>
      ))}
      {rows.some((c) => !c.connected) && (
        <div className="flex justify-end px-2 pb-1">
          <button onClick={() => skip(names)}
                  className="cursor-pointer rounded-full px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground">
            {t("notNow")}
          </button>
        </div>
      )}
    </div>
  );
}
