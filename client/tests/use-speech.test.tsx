// Voice input records in a format the browser has (Firefox can't record mp4), uploads it
// under that format's name, turns the mic off when it can't start, and draws a live wave.
import { renderHook, render, act, waitFor } from "@testing-library/react";
import { describe, test, expect, vi, afterEach } from "vitest";

const track = vi.hoisted(() => vi.fn());
vi.mock("../src/lib/analytics", () => ({ track }));

import { useSpeechRecognition } from "../src/hooks/use-speech";
import { LiveWaveform } from "../src/components/live-waveform";

function browser(supported: string[], { refuse }: { refuse?: string } = {}) {
  const stopTrack = vi.fn();
  const stream = { getTracks: () => [{ stop: stopTrack }] };
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia: vi.fn(async () => { if (refuse) throw new DOMException("no", refuse); return stream; }) },
  });
  const made: (MediaRecorderOptions | undefined)[] = [];
  class Recorder {
    static isTypeSupported = (type: string) => supported.includes(type);
    mimeType: string;
    ondataavailable: ((e: { data: Blob }) => void) | null = null;
    onstop: (() => void) | null = null;
    constructor(_: unknown, options?: MediaRecorderOptions) {
      if (options?.mimeType && !supported.includes(options.mimeType)) throw new DOMException("no", "NotSupportedError");
      this.mimeType = options?.mimeType ?? "";
      made.push(options);
    }
    start() {}
    stop() { this.ondataavailable?.({ data: new Blob([new Uint8Array(2000)]) }); this.onstop?.(); }
  }
  vi.stubGlobal("MediaRecorder", Recorder);
  const fetch = vi.fn(async (..._: unknown[]) => new Response(JSON.stringify({ text: "hi" })));
  vi.stubGlobal("fetch", fetch);
  const uploaded = () => ((fetch.mock.calls[0][1] as RequestInit).body as FormData).get("file") as File;
  return { made, stopTrack, uploaded };
}

async function speak() {
  const onEnd = vi.fn();
  const { result } = renderHook(() => useSpeechRecognition({ onEnd }));
  await act(async () => { await result.current.start(); });
  await act(async () => { result.current.stop(); });
  await waitFor(() => expect(onEnd).toHaveBeenCalled());
  return { result, onEnd };
}

afterEach(() => { vi.unstubAllGlobals(); track.mockClear(); });

describe("voice input", () => {
  test("Firefox records webm and uploads it as webm", async () => {
    const b = browser(["audio/webm;codecs=opus", "audio/ogg;codecs=opus"]);
    const { onEnd } = await speak();
    expect(b.made[0]?.mimeType).toBe("audio/webm;codecs=opus");
    expect(b.uploaded().name).toBe("voice.webm");
    expect(b.uploaded().type).toBe("audio/webm;codecs=opus");
    expect(onEnd).toHaveBeenCalledWith("hi");
  });

  test("Safari and Chrome keep recording mp4, uploaded as m4a", async () => {
    const b = browser(["audio/mp4", "audio/webm;codecs=opus"]);
    await speak();
    expect(b.made[0]?.mimeType).toBe("audio/mp4");
    expect(b.uploaded().name).toBe("voice.m4a");
  });

  test("a mic that can't start is turned off, reported by its reason, and said", async () => {
    const b = browser(["audio/mp4"]);
    vi.stubGlobal("MediaRecorder", Object.assign(function () { throw new DOMException("no", "NotSupportedError"); },
                                                 { isTypeSupported: () => true }));
    const { result } = renderHook(() => useSpeechRecognition({ onEnd: vi.fn() }));
    await act(async () => { await result.current.start(); });
    expect(b.stopTrack).toHaveBeenCalled();
    expect(track).toHaveBeenCalledWith("mic_permission_denied", { reason: "NotSupportedError" });
    expect(result.current.listening).toBe(false);

    browser([], { refuse: "NotAllowedError" });
    await act(async () => { await result.current.start(); });
    expect(track).toHaveBeenLastCalledWith("mic_permission_denied", { reason: "NotAllowedError" });
  });

  test("while recording, the hook hands out the mic's level, and lets it go after", async () => {
    browser(["audio/webm;codecs=opus"]);
    const close = vi.fn(async () => {});
    vi.stubGlobal("AudioContext", class {
      createAnalyser() { return { fftSize: 0 }; }
      createMediaStreamSource() { return { connect: () => {} }; }
      close = close;
    });
    const onEnd = vi.fn();
    const { result } = renderHook(() => useSpeechRecognition({ onEnd }));
    await act(async () => { await result.current.start(); });
    expect(result.current.analyser).toMatchObject({ fftSize: 256 });
    await act(async () => { result.current.stop(); });
    expect(result.current.analyser).toBeNull();
    expect(close).toHaveBeenCalled();
  });

  test("✕ while recording throws the audio away: nothing is uploaded", async () => {
    const b = browser(["audio/webm;codecs=opus"]);
    const onEnd = vi.fn();
    const { result } = renderHook(() => useSpeechRecognition({ onEnd }));
    await act(async () => { await result.current.start(); });
    await act(async () => { result.current.cancel(); });
    expect(onEnd).toHaveBeenCalledWith("");
    expect(b.stopTrack).toHaveBeenCalled();
    expect(result.current.listening).toBe(false);
    expect(fetch).not.toHaveBeenCalled();
  });

  test("the waveform scrolls in from the right: silence is dots, the voice is bars", () => {
    const frames: FrameRequestCallback[] = [];
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => frames.push(cb));
    vi.stubGlobal("cancelAnimationFrame", () => {});
    const bars: { x: number; h: number }[] = [];
    const ctx = new Proxy({ roundRect: (x: number, _y: number, _w: number, h: number) => bars.push({ x, h }),
                            createLinearGradient: () => ({ addColorStop: () => {} }) },
                          { get: (t, k) => (k in t ? t[k as keyof typeof t] : () => {}), set: () => true });
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(ctx as unknown as CanvasRenderingContext2D);
    vi.spyOn(HTMLCanvasElement.prototype, "getBoundingClientRect").mockReturnValue({ width: 60, height: 32 } as DOMRect);
    let level = 0;
    const analyser = { frequencyBinCount: 128, getByteFrequencyData: (d: Uint8Array) => d.fill(level) } as unknown as AnalyserNode;
    render(<LiveWaveform analyser={analyser} />);
    act(() => { frames.at(-1)?.(0); });
    expect(bars).toHaveLength(10);                                    // 60px of 3px bars, 3px apart
    expect(bars.every((b) => b.h === 3)).toBe(true);                 // silence: dots
    bars.length = 0;
    level = 255;
    act(() => { frames.at(-1)?.(100); });
    const newest = bars.reduce((a, b) => (b.x > a.x ? b : a));
    expect(newest.h).toBeGreaterThan(20);                            // the voice enters on the right
    expect(bars.filter((b) => b.h === 3)).toHaveLength(9);           // the rest is still the silence before
  });
});
