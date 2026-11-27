import { describe, it, expect, vi, afterEach } from "vitest";
import { render, cleanup, act } from "@testing-library/react";
import { useWarmService, WARM_AFTER } from "../src/lib/warm";

// The design editor's service sleeps when unused; the app wakes it once as it starts, not when a design opens.
function Probe({ base }: { base?: string }) { useWarmService(base); return null; }

describe("waking the design editor's service", () => {
  afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });

  it("asks its /health once, a moment after the app is up, and reads nothing back", async () => {
    vi.useFakeTimers();
    const fetch = vi.fn(async () => new Response(null));
    vi.stubGlobal("fetch", fetch);
    const { rerender } = render(<Probe base="https://ed.example/" />);
    expect(fetch).not.toHaveBeenCalled();                       // the app's own requests go first
    await act(async () => { vi.advanceTimersByTime(WARM_AFTER); });
    expect(fetch).toHaveBeenCalledOnce();
    expect(fetch).toHaveBeenCalledWith("https://ed.example/health", { mode: "no-cors", cache: "no-store", credentials: "omit" });
    rerender(<Probe base="https://ed.example/" />);
    await act(async () => { vi.advanceTimersByTime(WARM_AFTER * 4); });
    expect(fetch).toHaveBeenCalledOnce();                       // once per page
  });

  it("does nothing without an editor, or when it can't be reached", async () => {
    vi.useFakeTimers();
    const fetch = vi.fn(async () => { throw new TypeError("offline"); });
    vi.stubGlobal("fetch", fetch);
    render(<Probe />);
    await act(async () => { vi.advanceTimersByTime(WARM_AFTER * 2); });
    expect(fetch).not.toHaveBeenCalled();
    cleanup();
    render(<Probe base="https://ed.example" />);
    await act(async () => { vi.advanceTimersByTime(WARM_AFTER); });
    expect(fetch).toHaveBeenCalledOnce();                       // its failure is swallowed
  });
});
