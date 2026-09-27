import { describe, it, expect, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useFileContent } from "../src/components/canvas";

// The canvas refetches an open document at the end of every agent turn (and a deck
// after every edit of it). A one-off failure — a 401 while a token refreshed — used
// to latch the error card even though every later fetch succeeded.

const file = { path: "designs/pitch.deck.json", name: "pitch.deck.json" };

describe("useFileContent", () => {
  it("a success clears an earlier failure", async () => {
    let fail = true;
    const readFile = vi.fn(async () => { if (fail) throw new Error("HTTP 401"); return "{\"slides\":[]}"; });
    const openFile = vi.fn(async () => "blob:x");
    const { result, rerender } = renderHook(({ k }) => useFileContent(file, readFile, openFile, k), { initialProps: { k: 0 } });
    await waitFor(() => expect(result.current.error).toBe(true));
    fail = false;
    rerender({ k: 1 });
    await waitFor(() => expect(result.current.content).toBe("{\"slides\":[]}"));
    expect(result.current.error).toBe(false);
  });

  it("a failed refetch keeps what's shown", async () => {
    let fail = false;
    const readFile = vi.fn(async () => { if (fail) throw new Error("HTTP 502"); return "v1"; });
    const openFile = vi.fn(async () => "blob:x");
    const { result, rerender } = renderHook(({ k }) => useFileContent(file, readFile, openFile, k), { initialProps: { k: 0 } });
    await waitFor(() => expect(result.current.content).toBe("v1"));
    fail = true;
    rerender({ k: 1 });
    await waitFor(() => expect(readFile).toHaveBeenCalledTimes(2));
    await new Promise((r) => setTimeout(r, 0));
    expect(result.current.content).toBe("v1");
    expect(result.current.error).toBe(false);
  });
});
