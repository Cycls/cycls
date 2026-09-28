import { describe, it, expect, vi, afterEach } from "vitest";
import { render, cleanup, fireEvent, screen, act, waitFor } from "@testing-library/react";
import { PresentMode } from "../src/components/present-mode";
import { AudienceView } from "../src/components/audience-view";
import { percents, qrPath, voteUrl, type DeckPoll, type PollApi } from "../src/lib/polls";

// Live polls: a poll slide opens its poll while it's presented and its tracks fill
// with the room's votes; a phone on the deck's public link (?vote=1) votes once and
// sees the results.

const key = (k: string) =>
  act(() => { document.body.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true })); });

const poll: DeckPoll = {
  question: "Tea or coffee?", options: ["Tea", "Coffee"],
  tracks: [{ x: 144, y: 300, w: 1100, h: 40 }, { x: 144, y: 430, w: 1100, h: 40 }],
  join: { x: 1396, y: 300, w: 380, h: 380 }, accent: "#b45309", dir: "ltr", size: [1920, 1080],
};

function fakeApi(link: string | null = null) {
  const api = {
    open: vi.fn(async () => ({ session: "s1" })),
    close: vi.fn(async () => {}),
    results: vi.fn(async () => ({ session: "s1", counts: [1, 3], total: 4 })),
    joinUrl: vi.fn(async () => link),
    makeLink: vi.fn(async () => "https://agent.example/shared/u/t?vote=1"),
  };
  return api as typeof api & PollApi;
}

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("polls lib", () => {
  it("percents, the vote link and the QR", () => {
    expect(percents([1, 3])).toEqual([25, 75]);
    expect(percents([0, 0])).toEqual([0, 0]);
    expect(voteUrl("https://a.example/shared/u/t?ws=w1")).toBe("https://a.example/shared/u/t?ws=w1&vote=1");
    const d = qrPath("https://a.example/shared/u/t?vote=1", 300);
    expect(d.startsWith("M")).toBe(true);
    expect(d.split("M").length).toBeGreaterThan(100);                 // one square per dark module
  });
});

describe("a poll slide, presented by its owner", () => {
  it("opens the poll, fills the tracks from the tally, and closes when the slide goes", async () => {
    const api = fakeApi();
    render(<PresentMode deck={{ slides: ["data:a", "data:b"], polls: [null, poll] }} onClose={() => {}} polls={api} />);
    expect(api.open).not.toHaveBeenCalled();                          // slide 1 isn't a poll
    key("ArrowRight");
    await waitFor(() => expect(api.open).toHaveBeenCalledWith(1, poll));
    await waitFor(() => expect(screen.getByTestId("poll-total").textContent).toMatch(/^4 /));
    const bars = screen.getAllByTestId("poll-bar").map((g) => g.querySelector("rect")!.getAttribute("style") ?? "");
    expect(bars[0]).toContain("scaleX(0.25)");
    expect(bars[1]).toContain("scaleX(0.75)");
    key("r");                                                         // restart: a fresh session
    await waitFor(() => expect(api.open).toHaveBeenCalledTimes(2));
    key("ArrowLeft");
    await waitFor(() => expect(api.close).toHaveBeenCalled());
  });

  it("offers to make the public link, then shows the join QR", async () => {
    const api = fakeApi(null);
    render(<PresentMode deck={{ slides: ["data:b"], polls: [poll] }} onClose={() => {}} polls={api} />);
    const make = await screen.findByTestId("poll-make-link");
    expect(screen.queryByTestId("poll-qr")).toBeNull();
    fireEvent.click(make);
    await waitFor(() => expect(screen.getByTestId("poll-qr")).toBeTruthy());
    expect(api.makeLink).toHaveBeenCalledOnce();
    expect(screen.getByTestId("present-counter").textContent).toBe("1 / 1");   // the click didn't advance
  });

  it("a shared deck presents a poll slide as drawn", () => {
    render(<PresentMode deck={{ slides: ["data:b"], polls: [poll] }} onClose={() => {}} />);
    expect(screen.queryByTestId("poll-overlay")).toBeNull();
  });
});

describe("the audience, on the deck's public link", () => {
  function serve(vote: (body: { option: number; voter: string }) => Response) {
    window.history.pushState({}, "", "/shared/user_1/tok?ws=w1&vote=1");
    const calls: [string, RequestInit | undefined][] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      calls.push([url, init]);
      if (url.startsWith("/share/user_1/tok/poll/vote")) return vote(JSON.parse(String(init?.body)));
      if (url.startsWith("/share/user_1/tok/poll/results")) return Response.json({ session: "s1", counts: [0, 1], total: 1 });
      if (url.startsWith("/share/user_1/tok/poll")) return Response.json({ open: true, session: "s1", question: "Tea or coffee?", options: ["Tea", "Coffee"] });
      return new Response("", { status: 404 });
    }));
    return calls;
  }

  it("votes once and sees the room", async () => {
    localStorage.clear();
    const calls = serve(() => Response.json({ session: "s1", counts: [0, 1], total: 1 }));
    render(<AudienceView />);
    fireEvent.click((await screen.findAllByTestId("audience-option"))[1]);
    await waitFor(() => expect(screen.getAllByTestId("audience-result")).toHaveLength(2));
    const [url, init] = calls.find(([u]) => u.includes("/poll/vote"))!;
    expect(url).toBe("/share/user_1/tok/poll/vote?ws=w1");
    const body = JSON.parse(String(init?.body));
    expect(body).toMatchObject({ session: "s1", option: 1 });
    expect(body.voter).toMatch(/^[0-9a-f]{32}$/);
    expect(localStorage.getItem("cycls_vote_s1")).toBe("1");
    expect(screen.getByTestId("audience-note").textContent).toMatch(/Thanks/);
    expect(screen.getAllByTestId("audience-result")[1].textContent).toContain("100%");
  });

  it("a second vote from the same phone says so", async () => {
    localStorage.clear();
    serve(() => Response.json({ detail: "You've already voted" }, { status: 409 }));
    render(<AudienceView />);
    fireEvent.click((await screen.findAllByTestId("audience-option"))[0]);
    await waitFor(() => expect(screen.getByTestId("audience-note").textContent).toMatch(/already voted/));
  });
});
