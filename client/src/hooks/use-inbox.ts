import { useCallback, useEffect, useRef, useState } from "react";
import { chime } from "../lib/chime";

// What concerns the person, from every workspace they are in (GET /inbox).
export interface InboxItem {
  id: string;
  kind: "mention" | "reply" | "away" | "routine";
  state?: "done" | "asks" | "approve" | "failed" | "stuck" | "paused";   // away: how the task ended; a routine's trouble
  by?: { id: string; name?: string; image?: string };
  ws?: string;
  chat?: string;
  turn?: string;
  title?: string;
  text?: string;
  at: string;
}

type Api = (path: string, init?: RequestInit & { silent?: boolean; json?: unknown }) => Promise<Response>;

const EVERY = 15000;

// The bell's side: how many came since it was last opened, read every 15 seconds while the app is in view and as a
// chat opens (opening it read what the bell had about it), and the list when it opens. Something new sounds once,
// unless it is about the chat in front of the person: that is read as it comes.
export function useInbox(api: Api, on: boolean, chatOpen?: string | null) {
  const [items, setItems] = useState<InboxItem[]>([]);
  const [unread, setUnread] = useState(0);
  const heard = useRef<string | null>(null);   // the newest known; null before the first look, which sounds nothing
  const here = useRef(chatOpen);
  here.current = chatOpen;

  const look = useCallback(async () => {
    const r = await (await api("/inbox?limit=1", { silent: true })).json();
    const newest: InboxItem | undefined = r.items?.[0];
    let unread = r.unread || 0;
    if (heard.current !== null && newest && newest.at > heard.current) {
      if (newest.chat && newest.chat === here.current && document.hasFocus())
        unread = (await (await api("/inbox/seen", { method: "POST", json: { chat: newest.chat }, silent: true })).json()).unread ?? unread;
      else chime();
    }
    heard.current = newest?.at ?? heard.current ?? "";
    setUnread(unread);
  }, [api]);

  useEffect(() => {
    if (!on) return;
    void look().catch(() => {});
    const id = setInterval(() => { if (document.visibilityState === "visible") look().catch(() => {}); }, EVERY);
    return () => clearInterval(id);
  }, [on, look, chatOpen]);

  const open = useCallback(async () => {
    const r = await (await api("/inbox", { silent: true })).json();
    setItems(r.items || []);
    setUnread(0);
    await api("/inbox/seen", { method: "POST", silent: true });
  }, [api]);

  return { items, unread, open };
}
