import { useCallback, useEffect, useMemo, useState } from "react";
import { percents, type PollTally } from "../lib/polls";
import { track } from "../lib/analytics";
import { t } from "../lib/i18n";
import { cn } from "../lib/utils";

// The audience's side of a live poll: a phone on the deck's public link with
// `?vote=1` (the QR the presenter shows). It follows whatever poll the presenter has
// open — checked every 2 s, so it moves to the next question by itself — votes once
// per poll (the phone keeps a random voter id; the server takes one vote per id), and
// then shows how the room is voting.

type OpenPoll = { open: true; session: string; question: string; options: string[]; slide?: number };
type Poll = OpenPoll | { open: false };

const HEX = "0123456789abcdef";
function voterId(): string {
  try {
    const kept = localStorage.getItem("cycls_voter");
    if (kept && /^[0-9a-f]{32}$/.test(kept)) return kept;
  } catch { /* private mode: a voter for this page only */ }
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  const id = Array.from(bytes, (b) => HEX[b >> 4] + HEX[b & 15]).join("");
  try { localStorage.setItem("cycls_voter", id); } catch { /* fine */ }
  return id;
}
const votedKey = (session: string) => `cycls_vote_${session}`;
function votedIn(session: string): number | null {
  try {
    const v = localStorage.getItem(votedKey(session));
    return v == null ? null : Number(v);
  } catch { return null; }
}

export function AudienceView() {
  const base = window.location.pathname.replace("/shared/", "/share/");
  const ws = new URLSearchParams(window.location.search).get("ws");
  const q = (extra = "") => {
    const p = new URLSearchParams(extra);
    if (ws) p.set("ws", ws);
    const s = p.toString();
    return s ? `?${s}` : "";
  };
  const voter = useMemo(voterId, []);
  const [poll, setPoll] = useState<Poll | null>(null);
  const [voted, setVoted] = useState<number | null>(null);
  const [tally, setTally] = useState<PollTally | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [gone, setGone] = useState(false);          // not a deck link any more (revoked, never was)

  // Follow the presenter: whatever poll is open now.
  useEffect(() => {
    let cancelled = false, timer = 0;
    const tick = async () => {
      try {
        const res = await fetch(`${base}/poll${q()}`);
        if (res.status === 404 || res.status === 401 || res.status === 403) { if (!cancelled) setGone(true); return; }
        if (res.ok && !cancelled) setPoll(await res.json());
      } catch { /* offline for a moment: try again */ }
      if (!cancelled) timer = window.setTimeout(tick, 2000);
    };
    tick();
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  const session = poll?.open ? poll.session : null;
  useEffect(() => {
    setNote(null);
    setTally(null);
    setVoted(session ? votedIn(session) : null);
  }, [session]);

  // Once this phone has voted: the room's votes, every 3 s.
  useEffect(() => {
    if (!session || voted == null) return;
    let cancelled = false, timer = 0;
    const tick = async () => {
      try {
        const res = await fetch(`${base}/poll/results${q(`session=${encodeURIComponent(session)}`)}`);
        if (res.ok && !cancelled) setTally(await res.json());
      } catch { /* next time */ }
      if (!cancelled) timer = window.setTimeout(tick, 3000);
    };
    tick();
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [session, voted]);   // eslint-disable-line react-hooks/exhaustive-deps

  const vote = useCallback(async (option: number) => {
    if (!session || sending) return;
    setSending(true);
    setNote(null);
    try {
      const res = await fetch(`${base}/poll/vote${q()}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session, option, voter }),
      });
      if (res.ok) {
        try { localStorage.setItem(votedKey(session), String(option)); } catch { /* fine */ }
        setVoted(option);
        setTally(await res.json());
        track("poll_voted", { options: poll && poll.open ? poll.options.length : 0 });
      } else if (res.status === 409) {
        const detail = (await res.json().catch(() => ({})))?.detail ?? "";
        if (/already/i.test(detail)) { setVoted(votedIn(session) ?? -1); setNote(t("pollAlready")); }
        else setNote(t("pollClosed"));
      } else {
        setNote(t("pollError"));
      }
    } catch {
      setNote(t("pollError"));
    } finally {
      setSending(false);
    }
  }, [session, sending, voter, poll]);   // eslint-disable-line react-hooks/exhaustive-deps

  const counts = tally?.counts;
  const pct = counts ? percents(counts) : null;

  return (
    <div className="flex min-h-[100dvh] flex-col items-center justify-center bg-background px-5 py-10 text-foreground">
      <div className="w-full max-w-md" data-testid="audience-view">
        {gone ? (
          <p className="text-center text-sm text-muted-foreground">{t("pollClosed")}</p>
        ) : !poll || !poll.open ? (
          <p className="animate-pulse text-center text-sm text-muted-foreground">{t("pollWaiting")}</p>
        ) : (
          <>
            <h1 dir="auto" className="mb-6 text-center text-2xl font-semibold leading-snug">{poll.question}</h1>
            <div className="flex flex-col gap-3">
              {poll.options.map((option, i) => (
                voted == null ? (
                  <button key={i} data-testid="audience-option" disabled={sending} onClick={() => vote(i)} dir="auto"
                          className="rounded-2xl border border-border bg-card px-5 py-4 text-start text-lg font-medium transition-colors hover:bg-muted active:scale-[0.99] disabled:opacity-60">
                    {option}
                  </button>
                ) : (
                  <div key={i} data-testid="audience-result" dir="auto"
                       className={cn("relative overflow-hidden rounded-2xl border px-5 py-4", i === voted ? "border-foreground" : "border-border")}>
                    <div className="absolute inset-y-0 start-0 bg-foreground/10 transition-[width] duration-700"
                         style={{ width: `${pct?.[i] ?? 0}%` }} />
                    <div className="relative flex items-center justify-between gap-3 text-lg">
                      <span className={cn(i === voted && "font-semibold")}>{option}</span>
                      <span className="tabular-nums text-muted-foreground" dir="ltr">{pct ? `${pct[i]}%` : ""}</span>
                    </div>
                  </div>
                )
              ))}
            </div>
            <p className="mt-5 text-center text-sm text-muted-foreground" data-testid="audience-note">
              {note ?? (voted != null ? t("pollThanks") : "")}
            </p>
          </>
        )}
      </div>
    </div>
  );
}
