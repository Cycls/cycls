import { encode } from "uqr";

// A Design `poll` slide: the service says where its tracks and join card are; present mode fills them.

export interface DeckPoll {
  question: string;
  options: string[];
  tracks: { x: number; y: number; w: number; h: number }[];   // slide pixels
  join: { x: number; y: number; w: number; h: number };
  accent?: string;
  ink?: string;
  muted?: string;
  dir?: "ltr" | "rtl";          // an Arabic slide's bars fill from the right
  size?: [number, number];      // the slide's size, for the overlay's coordinates
}

export interface PollTally {
  session: string;
  counts: number[];
  total: number;
}

// The owner's; a shared deck has none.
export interface PollApi {
  open(slide: number, poll: DeckPoll): Promise<{ session: string }>;
  close(session: string): Promise<void>;
  results(session: string): Promise<PollTally>;
  joinUrl(): Promise<string | null>;   // the deck's public link, for voting — if it has one
  makeLink(): Promise<string>;         // make one (the presenter's click)
}

export function voteUrl(shareUrl: string): string {
  const u = new URL(shareUrl, window.location.origin);
  u.searchParams.set("vote", "1");
  return u.toString();
}

// The service's qrPath, same encoder: `size` square with a 2-module quiet zone.
export function qrPath(text: string, size: number): string {
  const { data } = encode(String(text), { ecc: "M", border: 0 });
  const n = data.length, q = 2, cell = size / (n + 2 * q);
  let d = "";
  for (let y = 0; y < n; y++)
    for (let x = 0; x < n; x++)
      if (data[y][x]) {
        const x0 = +((x + q) * cell).toFixed(2), y0 = +((y + q) * cell).toFixed(2);
        const s = +cell.toFixed(2) + 0.02;   // a hair wider, so neighbours don't show seams
        d += `M${x0} ${y0}h${s}v${s}h${-s}z`;
      }
  return d;
}

export function percents(counts: number[]): number[] {
  const total = counts.reduce((a, b) => a + b, 0);
  return counts.map((c) => (total ? Math.round((c / total) * 100) : 0));
}
