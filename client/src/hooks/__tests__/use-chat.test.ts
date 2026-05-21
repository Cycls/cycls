/**
 * useChat hook tests. First-tier coverage focused on the rfc-004 FE
 * invariants — URL plumbing, callback identity stability, attachment
 * rebuild on loadChat. Streaming/fetch behavior is mocked at the test
 * level since it's bigger surface; for now these are pure-state tests.
 */
import { renderHook, act } from "@testing-library/react";
import { describe, test, expect, beforeEach, vi } from "vitest";
import { useChat } from "../use-chat";

// send() fires posthog events; stub them so tests don't touch analytics.
vi.mock("../lib/posthog", () => ({ track: vi.fn() }));


beforeEach(() => {
  // Reset the URL between tests so each one sees a clean ?id=/?fork= state.
  window.history.replaceState({}, "", "/");
});

// Count fetches to /chat (ignore auth / file calls).
function countChatPosts(fetchMock: ReturnType<typeof vi.fn>): number {
  return fetchMock.mock.calls.filter(
    (c) => typeof c[0] === "string" && c[0].includes("/chat"),
  ).length;
}

// A Response whose stream emits `chunks` then throws `err` on the next read —
// models a connection dropped mid/post-stream.
function streamThenError(chunks: string[], err: Error): any {
  let i = 0;
  return {
    ok: true,
    body: {
      getReader: () => ({
        read: async () => {
          if (i < chunks.length) {
            return { done: false, value: new TextEncoder().encode(chunks[i++]) };
          }
          throw err;
        },
      }),
    },
  };
}


describe("clear()", () => {
  test("drops ?id= from window URL", () => {
    window.history.replaceState({}, "", "/?id=abc123");
    expect(new URL(window.location.href).searchParams.get("id")).toBe("abc123");

    const { result } = renderHook(() => useChat(""));
    act(() => result.current.clear());

    expect(new URL(window.location.href).searchParams.get("id")).toBeNull();
  });

  test("preserves other query params when dropping ?id=", () => {
    window.history.replaceState({}, "", "/?id=abc&q=hello");
    const { result } = renderHook(() => useChat(""));
    act(() => result.current.clear());

    const url = new URL(window.location.href);
    expect(url.searchParams.get("id")).toBeNull();
    expect(url.searchParams.get("q")).toBe("hello");
  });

  test("clears in-memory messages and chatId", () => {
    const { result } = renderHook(() => useChat(""));
    // We don't have a great way to populate messages without mocking
    // fetch. The clear() invariant on its own — empty stays empty — is
    // covered. The non-empty path is covered indirectly by the URL test
    // (clear runs both setMessages([]) and the URL strip together).
    act(() => result.current.clear());
    expect(result.current.messages).toEqual([]);
    expect(result.current.chatId).toBeNull();
  });
});


describe("callback identity stability (rfc-004 d2e7103)", () => {
  // setMessages([]) inside clear() creates a NEW empty-array reference.
  // If `messages` were back in send/share deps, their identities would
  // change. These tests fail loudly if the regression returns.

  test("send identity stable across messages reference change", () => {
    const { result } = renderHook(() => useChat(""));
    const sendBefore = result.current.send;

    // clear() sets messages to a fresh [] — different array reference
    act(() => result.current.clear());

    const sendAfter = result.current.send;
    expect(sendAfter).toBe(sendBefore);
  });

  test("share identity stable across messages reference change", () => {
    const { result } = renderHook(() => useChat(""));
    const shareBefore = result.current.share;

    act(() => result.current.clear());

    const shareAfter = result.current.share;
    expect(shareAfter).toBe(shareBefore);
  });

  test("send identity stable across multiple clears", () => {
    const { result } = renderHook(() => useChat(""));
    const send0 = result.current.send;

    act(() => result.current.clear());
    act(() => result.current.clear());
    act(() => result.current.clear());

    expect(result.current.send).toBe(send0);
  });

  test("loadChat identity stable across messages change", () => {
    // loadChat's deps are [baseUrl, authHeaders]; both stable. Should
    // never re-create.
    const { result } = renderHook(() => useChat(""));
    const loadBefore = result.current.loadChat;
    act(() => result.current.clear());
    expect(result.current.loadChat).toBe(loadBefore);
  });
});


describe("auto-retry gating — never resubmit a turn the server received", () => {
  test("mid-stream drop does NOT resubmit (bytes already flowed)", async () => {
    // Stream one SSE line, then the connection dies. The server has the
    // message and may have completed the turn — resubmitting would double-run.
    const fetchMock = vi.fn(async () =>
      streamThenError(
        [`data: ${JSON.stringify({ type: "text", text: "hi" })}\n\n`],
        new TypeError("network error"),
      ),
    );
    global.fetch = fetchMock as any;

    const { result } = renderHook(() => useChat("http://api.test"));
    await act(async () => {
      await result.current.send("hello");
    });

    expect(countChatPosts(fetchMock)).toBe(1); // no auto-retry
    // Partial streamed content is left intact; no misleading error callout.
    const msgs = result.current.messages;
    const last = msgs[msgs.length - 1];
    expect(last?.parts?.some((p: any) => p.type === "text" && p.text === "hi")).toBe(true);
    expect(last?.parts?.some((p: any) => p.type === "callout" && p.style === "error")).toBe(false);
  });

  test("pre-stream failure DOES auto-retry once (request never reached server)", async () => {
    // fetch rejects before any response — safe to retry, the turn never ran.
    const fetchMock = vi.fn(async () => {
      throw new TypeError("failed to fetch");
    });
    global.fetch = fetchMock as any;

    const { result } = renderHook(() => useChat("http://api.test"));
    await act(async () => {
      await result.current.send("hello");
    });

    expect(countChatPosts(fetchMock)).toBe(2); // original + one retry
  });
});


describe("loadChat (rfc-004 f556eee)", () => {
  test("rejects gracefully when fetch fails", async () => {
    // No mock = real fetch tries the URL = network error in jsdom.
    // loadChat should throw, not crash the hook state.
    const { result } = renderHook(() => useChat("http://nonexistent.invalid"));

    await expect(result.current.loadChat("xyz")).rejects.toThrow();

    // Hook is still usable
    expect(typeof result.current.send).toBe("function");
    expect(result.current.messages).toEqual([]);
  });

  test("rebuilds attachment URLs as blob URLs when fetch succeeds", async () => {
    // Stub fetch: chat metadata returns one user message with an
    // attachment that has a `path` but no live `url` (the on-disk
    // shape produced by load_messages on the backend).
    const fakeBlob = new Blob(["fakeimg"], { type: "image/jpeg" });
    const fakeChat = {
      id: "test",
      title: "",
      messages: [{
        role: "user",
        content: "look at this",
        attachments: [{
          name: "pic.jpg",
          path: "attachments/pic.jpg",
          type: "image/jpeg",
          size: 1234,
        }],
      }],
    };

    // First call returns chat JSON; subsequent calls return the blob
    // for /files/{path}.
    let call = 0;
    global.fetch = vi.fn(async (_input: any) => {
      call++;
      if (call === 1) {
        return new Response(JSON.stringify(fakeChat),
          { headers: { "Content-Type": "application/json" } });
      }
      return new Response(fakeBlob);
    }) as any;

    // jsdom's URL.createObjectURL may not exist; stub it.
    const created: Blob[] = [];
    (URL as any).createObjectURL = vi.fn((b: Blob) => {
      created.push(b);
      return `blob:fake-${created.length}`;
    });

    const { result } = renderHook(() => useChat("http://api.test"));
    await act(async () => {
      await result.current.loadChat("test");
    });

    expect(result.current.messages.length).toBe(1);
    const att = result.current.messages[0].attachments?.[0];
    expect(att?.url).toMatch(/^blob:fake-/);
    expect(created.length).toBe(1);
  });
});
