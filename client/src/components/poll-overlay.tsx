import { useEffect, useMemo, useRef, useState } from "react";
import { percents, qrPath, type DeckPoll, type PollApi, type PollTally } from "../lib/polls";
import { track } from "../lib/analytics";
import { t } from "../lib/i18n";

// Open while the slide shows, polled since the server runs on several instances (nothing to push from).
export function useLivePoll(api: PollApi | undefined, poll: DeckPoll | null | undefined, slide: number, restart: number) {
  const [tally, setTally] = useState<PollTally | null>(null);
  const queue = useRef<Promise<unknown>>(Promise.resolve());   // opens and closes reach the server in order
  useEffect(() => {
    setTally(null);
    if (!api || !poll) return;
    let cancelled = false, timer = 0;
    const opened: Promise<string | null> = queue.current.then(() => api.open(slide, poll).then((r) => r.session, () => null));
    queue.current = opened;
    (async () => {
      const session = await opened;
      if (!session || cancelled) return;                 // couldn't open: the slide stays as drawn
      track("poll_opened", { options: poll.options.length });
      const tick = async () => {
        try {
          const r = await api.results(session);
          if (!cancelled) setTally(r);
        } catch { /* the next tick tries again */ }
        if (!cancelled) timer = window.setTimeout(tick, 1500);
      };
      tick();
    })();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      queue.current = opened.then((session) => { if (session) return api.close(session).catch(() => {}); });
    };
  }, [api, poll, slide, restart]);
  return tally;
}

// In the slide's own coordinates: the image and this SVG are both contained in one box, so they line up at any size.
export function PollOverlay({ poll, tally, joinUrl, onMakeLink }: {
  poll: DeckPoll;
  tally: PollTally | null;
  joinUrl: string | null | undefined;     // undefined: still looking
  onMakeLink?: () => Promise<void>;
}) {
  const [W, H] = poll.size ?? [1920, 1080];
  const u = W / 1920;
  const counts = tally?.counts ?? poll.options.map(() => 0);
  const pct = percents(counts);
  const total = tally?.total ?? 0;
  const accent = poll.accent ?? "#2563eb", ink = poll.ink ?? "#111111", muted = poll.muted ?? "#6b7280";
  const rtl = poll.dir === "rtl";
  const j = poll.join;
  const qr = useMemo(() => (joinUrl ? qrPath(joinUrl, j.w) : ""), [joinUrl, j.w]);
  const [making, setMaking] = useState(false);
  return (
    <svg data-testid="poll-overlay" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet"
         className="pointer-events-none absolute inset-0 h-full w-full">
      {poll.tracks.map((tr, i) => (
        <g key={i} data-testid="poll-bar">
          <rect x={tr.x} y={tr.y} width={tr.w} height={tr.h} rx={tr.h / 2} fill={accent}
                style={{ transform: `scaleX(${pct[i] / 100})`, transformBox: "fill-box",
                         transformOrigin: rtl ? "right" : "left", transition: "transform 700ms ease-out" }} />
          {total > 0 && (
            <text x={rtl ? tr.x : tr.x + tr.w} y={tr.y - tr.h * 0.45} textAnchor={rtl ? "start" : "end"}
                  fontSize={tr.h * 0.75} fontWeight={600} fill={ink} direction="ltr"
                  style={{ fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif" }}>
              {pct[i]}% · {counts[i]}
            </text>
          )}
        </g>
      ))}
      {qr && (
        <g data-testid="poll-qr" transform={`translate(${j.x} ${j.y})`}>
          <rect width={j.w} height={j.h} rx={24 * u} fill="#ffffff" />
          <path d={qr} fill="#111111" />
        </g>
      )}
      {joinUrl === null && onMakeLink && (
        <foreignObject x={j.x} y={j.y} width={j.w} height={j.h}>
          <div className="flex h-full w-full items-center justify-center p-[6%]">
            <button data-testid="poll-make-link" disabled={making}
                    onClick={(e) => { e.stopPropagation(); setMaking(true); onMakeLink().finally(() => setMaking(false)); }}
                    className="pointer-events-auto rounded-xl bg-black/80 px-[8%] py-[6%] text-center font-medium leading-snug text-white shadow-lg hover:bg-black"
                    style={{ fontSize: 28 * u }}>
              {making ? t("pollLinking") : t("pollLink")}
            </button>
          </div>
        </foreignObject>
      )}
      <text x={j.x + j.w / 2} y={j.y + j.h + 110 * u} textAnchor="middle" fontSize={30 * u} fontWeight={600} fill={muted}
            style={{ fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif" }} data-testid="poll-total">
        {total} {total === 1 ? t("pollVote") : t("pollVotes")}
      </text>
    </svg>
  );
}
