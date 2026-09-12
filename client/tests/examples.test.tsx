/**
 * Examples gallery — the artifact derivation a shared chat opens by default,
 * and the /examples fetch hook (one request, module-cached).
 */
import { renderHook, waitFor } from "@testing-library/react";
import { describe, test, expect, vi } from "vitest";
import { canvasArtifacts } from "../src/components/shared-view";
import { useExamples } from "../src/components/examples";
import type { Message } from "../src/hooks/use-chat";

vi.mock("../src/lib/analytics", () => ({ track: vi.fn() }));

describe("canvasArtifacts", () => {
  test("collects successful Canvas steps in order, skipping errors and repeats", () => {
    const messages: Message[] = [
      { role: "user", content: "make a site" },
      {
        role: "assistant",
        content: "",
        parts: [
          { type: "step", tool_name: "Canvas", step: "draft.html" },
          { type: "step", tool_name: "Canvas", step: "broken.html", ok: false },
          { type: "step", tool_name: "Bash", step: "ls" },
          { type: "step", tool_name: "Canvas", step: "site.html" },
          { type: "step", tool_name: "Canvas", step: "site.html" }, // retry — same file
        ],
      },
    ];
    expect(canvasArtifacts(messages)).toEqual(["draft.html", "site.html"]);
  });

  test("empty for conversations without canvas output", () => {
    expect(canvasArtifacts([{ role: "user", content: "hi" }])).toEqual([]);
    expect(canvasArtifacts([{ role: "assistant", content: "hello", parts: [{ type: "text", text: "hello" }] }])).toEqual([]);
  });
});

describe("useExamples", () => {
  test("fetches /examples once and caches across mounts", async () => {
    const categories = [{ label: "Sites", items: [{ share: "/shared/u/t?example=1", title: "T", prompt: "p", file: null }] }];
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ categories }) });
    vi.stubGlobal("fetch", fetchMock);

    const first = renderHook(() => useExamples());
    await waitFor(() => expect(first.result.current).toEqual(categories));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith("/examples");

    // A remount (every new chat) serves from the module cache — no refetch.
    const second = renderHook(() => useExamples());
    expect(second.result.current).toEqual(categories);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
