import { useEffect, useState } from "react";
import { followDesignPeer, useDesignPresence, type DesignPeer } from "./design-editor-view";
import { t } from "../lib/i18n";
import { cn } from "../lib/utils";

// Who else has this design open in its editor right now — a row of their initials,
// each ringed in the colour of their cursor, beside the Edit | Preview switch. Clicking
// one keeps this person's view in step with theirs (again to stop). Nothing is shown
// while nobody else is in the design.
const SHOWN = 4;
const initial = (name: string) => (name.trim()[0] ?? "?").toUpperCase();

export function DesignPresenceRow({ path }: { path: string }) {
  const presence = useDesignPresence(path);
  const [following, setFollowing] = useState<number | null>(null);
  const peers = presence?.peers ?? [];
  const followed = peers.find((p) => p.client === following) ?? null;
  // The one followed left the design: there is nobody to follow.
  useEffect(() => {
    if (following !== null && !followed) setFollowing(null);
  }, [following, followed]);
  if (!peers.length) return null;

  const follow = (peer: DesignPeer) => {
    const next = following === peer.client ? null : peer.client;
    setFollowing(next);
    followDesignPeer(path, next);
  };
  const label = (peer: DesignPeer) =>
    t(following === peer.client ? "stopFollowing" : "followPerson").replace("{name}", peer.name || t("someone"));

  return (
    <div className="flex shrink-0 items-center" data-testid="design-presence" dir="ltr">
      {peers.slice(0, SHOWN).map((peer) => (
        <button
          key={peer.client}
          onClick={() => follow(peer)}
          title={label(peer)}
          aria-label={label(peer)}
          aria-pressed={following === peer.client}
          style={{ borderColor: peer.color ?? undefined }}
          className={cn(
            "-ml-1.5 flex size-6 items-center justify-center rounded-full border-2 bg-background text-[10px] font-semibold text-foreground transition-transform first:ml-0 hover:z-10 hover:scale-110 cursor-pointer",
            following === peer.client && "ring-2 ring-foreground/60",
          )}
        >
          {initial(peer.name)}
        </button>
      ))}
      {peers.length > SHOWN && (
        <span className="-ml-1.5 flex size-6 items-center justify-center rounded-full border-2 border-border bg-secondary text-[10px] text-muted-foreground">
          +{peers.length - SHOWN}
        </span>
      )}
      {followed && (
        <span className="ml-2 max-w-28 truncate text-xs text-muted-foreground">
          {t("followingPerson").replace("{name}", followed.name || t("someone"))}
        </span>
      )}
    </div>
  );
}
