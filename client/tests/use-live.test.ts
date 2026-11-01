// A live conversation opens its call through the server, hands what needs the agent to the chat as a spoken
// turn, and gives the reply back to the voice once it ends.
import { renderHook, act, waitFor } from "@testing-library/react";
import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("../src/lib/analytics", () => ({ track: vi.fn() }));
const toastError = vi.hoisted(() => vi.fn());
vi.mock("../src/lib/toast", () => ({ useToast: () => ({ error: toastError }) }));

import { useLive } from "../src/hooks/use-live";
import type { Message } from "../src/hooks/use-chat";

let channel: { readyState: string; sent: unknown[]; send: (s: string) => void; close: () => void; onopen?: () => void; onmessage?: (e: { data: string }) => void };
let remote: RTCSessionDescriptionInit | undefined;
beforeEach(() => {
  remote = undefined;
  channel = { readyState: "open", sent: [], send(s) { this.sent.push(JSON.parse(s)); }, close: vi.fn() };
  vi.stubGlobal("RTCPeerConnection", class {
    ontrack = null;
    addTrack = vi.fn();
    getSenders = () => [];
    close = vi.fn();
    createDataChannel = () => channel;
    createOffer = async () => ({ type: "offer", sdp: "v=0 offer" });
    setLocalDescription = async () => {};
    setRemoteDescription = async (d: RTCSessionDescriptionInit) => { remote = d; };
  });
  vi.stubGlobal("Audio", class { autoplay = false; srcObject = null; });
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: async () => ({ getTracks: () => [{ stop: vi.fn() }] }) } });
  vi.stubGlobal("fetch", vi.fn(async () => new Response("v=0 answer")));
});
afterEach(() => vi.unstubAllGlobals());

const event = (ev: object) => act(() => channel.onmessage?.({ data: JSON.stringify(ev) }));
const reply = (text: string): Message => ({ role: "assistant", content: "", parts: [{ type: "text", text }] });

describe("a live conversation", () => {
  test("the server opens the call; a request goes to the chat and its reply back to the voice", async () => {
    const send = vi.fn();
    const { result, rerender } = renderHook((p: { messages: Message[]; isStreaming: boolean }) => useLive({ ...p, send }),
      { initialProps: { messages: [] as Message[], isStreaming: false } });
    await act(async () => { await result.current.start(); });
    expect(fetch).toHaveBeenCalledWith("/realtime", expect.objectContaining({ method: "POST", body: "v=0 offer" }));
    expect(remote).toEqual({ type: "answer", sdp: "v=0 answer" });
    act(() => channel.onopen?.());
    expect(result.current.phase).toBe("listening");

    event({ type: "output_audio_buffer.started" });
    expect(result.current.phase).toBe("speaking");
    event({ type: "response.done", response: { output: [
      { type: "message" },
      { type: "function_call", name: "ask_agent", call_id: "c1", arguments: JSON.stringify({ request: "وش الطقس في الرياض؟", language: "Arabic" }) }] } });
    expect(send).toHaveBeenCalledWith("وش الطقس في الرياض؟", "Arabic");
    expect(result.current.phase).toBe("thinking");

    const user: Message = { role: "user", content: "وش الطقس في الرياض؟" };
    rerender({ messages: [user, reply("")], isStreaming: true });
    rerender({ messages: [user, reply("الجو **حار**، 41 درجة.\n| a | b |")], isStreaming: true });
    expect(channel.sent).toEqual([]);   // not before it ends
    rerender({ messages: [user, reply("الجو **حار**، 41 درجة.\n| a | b |")], isStreaming: false });
    await waitFor(() => expect(channel.sent).toEqual([
      { type: "conversation.item.create", item: { type: "function_call_output", call_id: "c1", output: "الجو حار، 41 درجة." } },
      { type: "response.create" },
    ]));
    expect(result.current.phase).toBe("listening");

    act(() => result.current.hush());
    expect(channel.sent.slice(2)).toEqual([{ type: "response.cancel" }, { type: "output_audio_buffer.clear" }]);
    act(() => result.current.end());
    expect(result.current.phase).toBe("off");
  });

  test("an error from the voice is said, not left as silence", async () => {
    const { result } = renderHook(() => useLive({ messages: [], isStreaming: false, send: vi.fn() }));
    await act(async () => { await result.current.start(); });
    act(() => channel.onopen?.());
    event({ type: "response.done", response: { status: "failed", status_details: { error: { code: "insufficient_quota" } } } });
    expect(result.current.phase).toBe("off");
    expect(toastError).toHaveBeenCalled();
  });

  test("a call the server can't open ends the conversation", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("no", { status: 501 })));
    const { result } = renderHook(() => useLive({ messages: [], isStreaming: false, send: vi.fn() }));
    await act(async () => { await result.current.start(); });
    expect(result.current.phase).toBe("off");
  });
});
