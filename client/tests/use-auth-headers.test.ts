/**
 * X-Workspace plumbing (workspace FE invariants): the module-level
 * active workspace reaches every hook instance's headers, null (= personal)
 * sends no header, and a share link's `?ws=` reattaches after /fork.
 */
import { renderHook } from "@testing-library/react";
import { describe, test, expect, afterEach, vi } from "vitest";
import { useAuthHeaders, setActiveWorkspace, fetchAuthed } from "../src/hooks/use-auth-headers";
import { useChat } from "../src/hooks/use-chat";
import { useFiles } from "../src/hooks/use-files";

vi.mock("../src/lib/analytics", () => ({ track: vi.fn() }));

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

  // App.tsx wires the token onto three hooks by name. Held per instance, any
  // FOURTH caller sends no Authorization at all and simply 401s — which is
  // exactly what happened to useApps and emptied the Apps tab.
  test("a hook instance nobody wired still authenticates", async () => {
    const wired = renderHook(() => useAuthHeaders());
    wired.result.current.setGetToken(async () => "tok");
    setActiveWorkspace(null);

    const unwired = renderHook(() => useAuthHeaders());
    expect(await unwired.result.current.authHeaders()).toEqual({
      Authorization: "Bearer tok",
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

// A tab left in the background: the browser throttles the token's refresh, the cached
// one goes stale, and the first request on coming back was a bare "HTTP 401".
describe("a stale token", () => {
  test("a 401 is asked once more with a token fetched afresh", async () => {
    const { result } = renderHook(() => useAuthHeaders());
    const tokens = vi.fn(async (fresh?: boolean) => (fresh ? "new" : "stale"));
    result.current.setGetToken(tokens);
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) =>
      new Response("", { status: (init.headers as Record<string, string>).Authorization === "Bearer new" ? 200 : 401 }));
    vi.stubGlobal("fetch", fetchMock);
    const res = await fetchAuthed("/chat", { method: "POST", body: "{}", headers: { "Content-Type": "application/json" } });
    expect(res.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(tokens.mock.calls.map((c) => !!c[0])).toEqual([false, true]);
    const again = fetchMock.mock.calls[1][1] as RequestInit;
    expect(again.method).toBe("POST");
    expect(again.body).toBe("{}");                                   // the same request, whole
    expect((again.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
  });

  test("a second 401 is the answer, and nothing else is asked twice", async () => {
    const { result } = renderHook(() => useAuthHeaders());
    result.current.setGetToken(async () => "tok");
    const always = vi.fn(async () => new Response("", { status: 401 }));
    vi.stubGlobal("fetch", always);
    expect((await fetchAuthed("/files")).status).toBe(401);
    expect(always).toHaveBeenCalledTimes(2);
    const forbidden = vi.fn(async () => new Response("", { status: 403 }));
    vi.stubGlobal("fetch", forbidden);
    expect((await fetchAuthed("/files")).status).toBe(403);
    expect(forbidden).toHaveBeenCalledTimes(1);
  });

  // The Studio opening a big scene: its engine call waits behind hundreds of file reads,
  // the token runs out meanwhile, and the app sat at "shaping the geometry… 0/97" for good.
  test("an app's engine call is asked once more too, and a refusal is still the app's to show", async () => {
    const auth = renderHook(() => useAuthHeaders());
    auth.result.current.setGetToken(async (fresh?: boolean) => (fresh ? "new" : "stale"));
    const files = renderHook(() => useFiles());
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) =>
      (init.headers as Record<string, string>).Authorization === "Bearer new"
        ? new Response(JSON.stringify({ ok: true }))
        : new Response("", { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);
    expect(await files.result.current.appEngine("studio", "evaluate", { scene: 1 })).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1][0]).toBe("/apps/studio/engine");
    expect(JSON.parse((fetchMock.mock.calls[1][1] as RequestInit).body as string)).toEqual({ scene: 1, op: "evaluate" });

    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "the engine is busy" }), { status: 429 })));
    await expect(files.result.current.appEngine("studio", "evaluate", {})).rejects.toMatchObject({ message: "the engine is busy", status: 429 });
  });
});
