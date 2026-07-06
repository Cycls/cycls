/**
 * X-Workspace plumbing (workspace FE invariants): the module-level
 * active workspace reaches every hook instance's headers, null (= personal)
 * sends no header, and a share link's `?ws=` reattaches after /fork.
 */
import { renderHook } from "@testing-library/react";
import { describe, test, expect, afterEach, vi } from "vitest";
import { useAuthHeaders, setActiveWorkspace } from "../use-auth-headers";
import { useChat } from "../use-chat";

vi.mock("../lib/posthog", () => ({ track: vi.fn() }));

afterEach(() => {
  setActiveWorkspace(null);
  vi.unstubAllGlobals();
});

describe("X-Workspace header", () => {
  test("absent by default (personal workspace)", async () => {
    const { result } = renderHook(() => useAuthHeaders());
    expect(await result.current.authHeaders()).toEqual({});
  });

  test("set on every hook instance once activated", async () => {
    const a = renderHook(() => useAuthHeaders());
    const b = renderHook(() => useAuthHeaders());
    setActiveWorkspace("t-abc123");
    expect((await a.result.current.authHeaders())["X-Workspace"]).toBe("t-abc123");
    expect((await b.result.current.authHeaders())["X-Workspace"]).toBe("t-abc123");
  });

  test("cleared when switching back to personal", async () => {
    const { result } = renderHook(() => useAuthHeaders());
    setActiveWorkspace("t-abc123");
    setActiveWorkspace(null);
    expect(await result.current.authHeaders()).toEqual({});
  });

  test("composes with the bearer token", async () => {
    const { result } = renderHook(() => useAuthHeaders());
    result.current.setGetToken(async () => "tok");
    setActiveWorkspace("u-user_1");
    expect(await result.current.authHeaders()).toEqual({
      Authorization: "Bearer tok",
      "X-Workspace": "u-user_1",
    });
  });
});

test("forkShare reattaches ?ws= after the /fork segment", async () => {
  const fetchMock = vi.fn(async (..._args: unknown[]) => new Response(JSON.stringify({ id: "n1" })));
  vi.stubGlobal("fetch", fetchMock);
  const { result } = renderHook(() => useChat());
  await result.current.forkShare("org_1:user_1/tok123?ws=t-abc");
  expect(fetchMock).toHaveBeenCalledWith("/share/org_1:user_1/tok123/fork?ws=t-abc",
    expect.objectContaining({ method: "POST" }));
});
