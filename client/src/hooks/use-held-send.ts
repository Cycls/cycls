import { useCallback, useEffect, useRef, useState } from "react";
import type { Attachment, SendExtra } from "./use-chat";

// A send pressed while a file is still uploading. It waits — the composer says so — and goes
// by itself once every upload is done, with the text and files as they are then. A failed
// upload drops it (the chip shows the failure, the text stays in the composer); so does any
// change to the text. Pressing send again while held changes nothing: it is the same send,
// and it goes once.
interface Hold {
  text: string;          // the composer's text when send was pressed
  origin: string;
  extra?: SendExtra;
  failed: Set<string>;   // attachments that had already failed then — known, not news
}

export const uploading = (attachments: Attachment[]) => attachments.some((a) => a.status === "uploading");

export function useHeldSend({ input, attachments, send }: {
  input: string;
  attachments: Attachment[];
  send: (origin: string, extra?: SendExtra) => void;   // the composer's own send, as it stands when called
}) {
  const [hold, setHold] = useState<Hold | null>(null);
  // The ref is what the effect reads and clears before it sends, so no re-render can send twice.
  const holdRef = useRef<Hold | null>(null);
  const sendRef = useRef(send);
  sendRef.current = send;
  const attachmentsRef = useRef(attachments);
  attachmentsRef.current = attachments;

  const cancel = useCallback(() => {
    holdRef.current = null;
    setHold(null);
  }, []);

  const request = useCallback((text: string, origin: string, extra?: SendExtra) => {
    const failed = holdRef.current?.failed
      ?? new Set(attachmentsRef.current.filter((a) => a.status === "error").map((a) => a.url));
    holdRef.current = { text: text.trim(), origin, extra, failed };
    setHold(holdRef.current);
  }, []);

  useEffect(() => {
    const h = holdRef.current;
    if (!h) return;
    if (input.trim() !== h.text) return cancel();
    if (attachments.some((a) => a.status === "error" && !h.failed.has(a.url))) return cancel();
    if (uploading(attachments)) return;
    cancel();
    sendRef.current(h.origin, h.extra);
  }, [hold, input, attachments, cancel]);

  return { held: hold !== null, request, cancel };
}
