// A voice conversation reads only what can be said, a finished sentence at a time while the reply streams,
// never with the mic on, and listens again once everything is said.
import { renderHook, act, waitFor } from "@testing-library/react";
import { describe, test, expect, vi, afterEach, beforeEach } from "vitest";

vi.mock("../src/lib/analytics", () => ({ track: vi.fn() }));

import { useTalk, speakable, sentences } from "../src/hooks/use-talk";
import type { Message } from "../src/hooks/use-chat";

const played: string[] = [];
class FakeAudio {
  src = "";
  onended: (() => void) | null = null;
  onerror: (() => void) | null = null;
  play = vi.fn(async () => { if (!this.src.startsWith("data:")) played.push(this.src); });
  pause = vi.fn();
}
let audios: FakeAudio[] = [];

beforeEach(() => {
  played.length = 0;
  audios = [];
  vi.stubGlobal("Audio", class extends FakeAudio { constructor() { super(); audios.push(this); } });
  vi.stubGlobal("fetch", vi.fn(async (_: string, init: RequestInit) =>
    new Response(new Blob([JSON.parse(init.body as string).text]), { status: 200 })));
  let n = 0;
  URL.createObjectURL = vi.fn(() => `blob:${++n}`);
  URL.revokeObjectURL = vi.fn();
});
afterEach(() => vi.unstubAllGlobals());

const spoken = () => (fetch as unknown as { mock: { calls: [string, RequestInit][] } }).mock.calls
  .map(([url, init]) => [url, JSON.parse(init.body as string).text]);
const reply = (text: string): Message => ({ role: "assistant", content: "", parts: [{ type: "text", text }] });

function talking() {
  const mic = { listening: false, transcribing: false, analyser: null, stop: vi.fn(), cancel: vi.fn(),
                start: vi.fn(async () => { mic.listening = true; return true; }) };
  const view = renderHook((p: { messages: Message[]; isStreaming: boolean }) => useTalk({ ...p, mic }),
    { initialProps: { messages: [] as Message[], isStreaming: false } });
  // The mic heard something: it is off again, and the chat sends the words.
  const said = (text: string) => { mic.listening = false; act(() => view.result.current.heard(text)); };
  return { mic, said, ...view };
}

describe("what a reply says out loud", () => {
  test("no code, table rows, addresses or marks; an open fence hides the rest", () => {
    expect(speakable("**Done.** See [the report](https://x.io/r) or https://x.io.\n| a | b |\n|---|---|\nNext.")).toBe("Done. See the report or \n\n\nNext.");
    expect(speakable("Run this:\n```py\nprint(1)\n```\nThat's it.")).toBe("Run this:\n \nThat's it.");
    expect(speakable("Run this:\n```py\nprint(1)")).toBe("Run this:\n");
    expect(speakable("Tell me more.</｜DSML｜ parameter> </｜DSML｜ invoke>")).toBe("Tell me more. ");
  });

  test("Arabic sentences end at ؟ and ! but not at ،", () => {
    expect(sentences("هلا والله! وش تبي؟ تمام، أبشر.").map((s) => s.trim())).toEqual(["هلا والله!", "وش تبي؟", "تمام، أبشر."]);
  });
});

describe("a voice conversation", () => {
  test("listens, reads each finished sentence as the reply streams, then listens again", async () => {
    const { mic, said, result, rerender } = talking();
    act(() => result.current.start());
    await waitFor(() => expect(mic.start).toHaveBeenCalledTimes(1));

    said("what's the weather");
    const user: Message = { role: "user", content: "what's the weather" };
    rerender({ messages: [user, reply("")], isStreaming: true });
    rerender({ messages: [user, reply("It's sunny in Riyadh. Around 31")], isStreaming: true });
    await waitFor(() => expect(spoken()).toEqual([["/speak", "It's sunny in Riyadh."]]));
    await waitFor(() => expect(played).toEqual(["blob:1"]));
    expect(result.current.phase).toBe("speaking");

    rerender({ messages: [user, reply("It's sunny in Riyadh. Around 31 degrees.\n```\ncode\n```")], isStreaming: false });
    await waitFor(() => expect(spoken().map(([, t]) => t)).toEqual(["It's sunny in Riyadh.", "Around 31 degrees."]));
    expect(mic.start).toHaveBeenCalledTimes(1);   // not while there is something left to say

    const el = audios[0];
    act(() => el.onended?.());
    await waitFor(() => expect(played).toEqual(["blob:1", "blob:2"]));
    act(() => el.onended?.());
    await waitFor(() => expect(result.current.phase).toBe("thinking"));
    await waitFor(() => expect(mic.start).toHaveBeenCalledTimes(2));   // all said: listening again
  });

  test("stop speaking drops the rest; ending turns the mic off and listens no more", async () => {
    const { mic, said, result, rerender } = talking();
    act(() => result.current.start());
    await waitFor(() => expect(mic.start).toHaveBeenCalledTimes(1));
    said("hi");
    const user: Message = { role: "user", content: "hi" };
    rerender({ messages: [user, reply("One. Two. Three. Four.")], isStreaming: true });
    await waitFor(() => expect(played).toHaveLength(1));
    act(() => result.current.hush());
    rerender({ messages: [user, reply("One. Two. Three. Four. Five.")], isStreaming: false });
    expect(spoken().map(([, t]) => t)).toEqual(["One.", "Two.", "Three."]);   // a few fetched ahead, no more
    expect(audios[0].pause).toHaveBeenCalled();
    await waitFor(() => expect(mic.start).toHaveBeenCalledTimes(2));

    act(() => result.current.end());
    expect(mic.cancel).toHaveBeenCalled();
    expect(result.current.phase).toBe("off");
  });

  test("a mic that can't start ends the conversation", async () => {
    const { mic, result } = talking();
    mic.start.mockImplementationOnce(async () => false);
    act(() => result.current.start());
    await waitFor(() => expect(result.current.phase).toBe("off"));
  });
});
