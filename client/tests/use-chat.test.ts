/**
 * useChat hook tests. First-tier coverage focused on the rfc-004 FE
 * invariants — URL plumbing, callback identity stability, attachment
 * rebuild on loadChat. Streaming/fetch behavior is mocked at the test
 * level since it's bigger surface; for now these are pure-state tests.
 */
import { renderHook, act } from "@testing-library/react";
import { describe, test, expect, beforeEach, vi } from "vitest";
import { useChat } from "../src/hooks/use-chat";

// send() fires posthog events; stub them so tests don't touch analytics.
vi.mock("../src/lib/analytics", () => ({ track: vi.fn() }));


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


function sseTurn(chatId: string, text: string): any {
  const body = [
    `data: ${JSON.stringify({ type: "chat_id", chat_id: chatId })}\n\n`,
    `data: ${JSON.stringify({ type: "text", text })}\n\n`,
  ].join("");
  let sent = false;
  return {
    ok: true,
    body: {
      getReader: () => ({
        read: async () => {
          if (sent) return { done: true, value: undefined };
          sent = true;
          return { done: false, value: new TextEncoder().encode(body) };
        },
      }),
    },
  };
}

describe("regenerate() — rewind the last exchange, then re-send it", () => {
  // A complete SSE turn: the server hands back a chat id, then some text.

  test("truncates on the server BEFORE re-sending, and replaces the exchange", async () => {
    const calls: { url: string; method?: string }[] = [];
    const fetchMock = vi.fn(async (url: any, init: any) => {
      calls.push({ url: String(url), method: init?.method });
      if (String(url).includes("last-exchange")) return { ok: true, json: async () => ({ ok: true }) };
      return sseTurn("c1", "second answer");
    });
    global.fetch = fetchMock as any;

    const { result } = renderHook(() => useChat("http://api.test"));
    await act(async () => { await result.current.send("hello"); });
    expect(result.current.messages.map((m) => m.role)).toEqual(["user", "assistant"]);

    await act(async () => { await result.current.regenerate(); });
    // regenerate defers the re-send by a macrotask so the truncated messages
    // commit (and messagesRef catches up) before send() reads them.
    await act(async () => { await new Promise((r) => setTimeout(r, 10)); });

    const truncateAt = calls.findIndex((c) => c.url.includes("last-exchange"));
    const resendAt = calls.findIndex((c, i) => i > truncateAt && c.url.includes("/chat"));
    expect(truncateAt).toBeGreaterThanOrEqual(0);
    expect(calls[truncateAt].method).toBe("DELETE");
    expect(calls[truncateAt].url).toContain("/chats/c1/last-exchange");
    // Ordering is the invariant: re-sending first would double the history.
    expect(resendAt).toBeGreaterThan(truncateAt);

    // One exchange, not two — the old assistant turn was replaced.
    expect(result.current.messages.map((m) => m.role)).toEqual(["user", "assistant"]);
    expect(result.current.messages[0].content).toBe("hello");
  });

  test("a failed truncate aborts rather than duplicating history", async () => {
    const fetchMock = vi.fn(async (url: any) => {
      if (String(url).includes("last-exchange")) {
        return { ok: false, status: 500, statusText: "boom", clone: () => ({ json: async () => ({}) }) };
      }
      return sseTurn("c1", "answer");
    });
    global.fetch = fetchMock as any;

    const { result } = renderHook(() => useChat("http://api.test"));
    await act(async () => { await result.current.send("hello"); });
    const sends = () => fetchMock.mock.calls.filter((c: any) => c[1]?.method === "POST").length;
    const before = sends();

    await act(async () => { await result.current.regenerate(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 10)); });

    // The DELETE 500s, so no re-send follows and history is untouched.
    expect(sends()).toBe(before);
    expect(result.current.messages.map((m) => m.role)).toEqual(["user", "assistant"]);
  });

  test("no-ops on an empty chat", async () => {
    const fetchMock = vi.fn();
    global.fetch = fetchMock as any;
    const { result } = renderHook(() => useChat("http://api.test"));
    await act(async () => { await result.current.regenerate(); });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});


describe("sources — citation parts from web search", () => {
  function sseLines(lines: string[]): any {
    const body = lines.map((l) => `data: ${l}\n\n`).join("");
    let sent = false;
    return {
      ok: true,
      body: {
        getReader: () => ({
          read: async () => {
            if (sent) return { done: true, value: undefined };
            sent = true;
            return { done: false, value: new TextEncoder().encode(body) };
          },
        }),
      },
    };
  }

  const rows = (host: string) => [{ title: `T ${host}`, url: `https://${host}/a`, snippet: "s" }];

  test("two parallel searches keep separate source lists", async () => {
    // Same-type parts are normally merged as text deltas; a `sources` array is
    // a whole value, so back-to-back events must not be concatenated.
    global.fetch = vi.fn(async () =>
      sseLines([
        JSON.stringify({ type: "step", id: "S1", tool_name: "Web Search", step: "a" }),
        JSON.stringify({ type: "sources", sources: rows("reuters.com") }),
        JSON.stringify({ type: "sources", sources: rows("argaam.com") }),
        JSON.stringify({ type: "text", text: "done" }),
      ]),
    ) as any;

    const { result } = renderHook(() => useChat("http://api.test"));
    await act(async () => { await result.current.send("hi"); });

    const parts = result.current.messages[1].parts!;
    const sources = parts.filter((p: any) => p.type === "sources");
    expect(sources).toHaveLength(2);
    expect(sources[0].sources).toEqual(rows("reuters.com"));
    expect(sources[1].sources).toEqual(rows("argaam.com"));
  });

  test("a sources part survives alongside the search step and the answer", async () => {
    global.fetch = vi.fn(async () =>
      sseLines([
        JSON.stringify({ type: "step", id: "S1", tool_name: "Web Search", step: "saudi gdp" }),
        JSON.stringify({ type: "sources", sources: rows("reuters.com") }),
        JSON.stringify({ type: "text", text: "It grew 4.9%." }),
      ]),
    ) as any;

    const { result } = renderHook(() => useChat("http://api.test"));
    await act(async () => { await result.current.send("hi"); });

    expect(result.current.messages[1].parts!.map((p: any) => p.type))
      .toEqual(["step", "sources", "text"]);
    expect(result.current.messages[1].content).toBe("It grew 4.9%.");
  });
});

describe("tool switches", () => {
  test("web search off rides the request as disabled_tools; on sends nothing extra", async () => {
    const bodies: any[] = [];
    global.fetch = vi.fn(async (_url: any, init: any) => {
      bodies.push(JSON.parse(init.body));
      return sseTurn("c1", "answer");
    }) as any;
    localStorage.setItem("cycls_web_search", "off");
    const { result } = renderHook(() => useChat("http://api.test"));
    await act(async () => { await result.current.send("hello"); });
    expect(bodies[0].disabled_tools).toEqual(["WebSearch"]);

    localStorage.removeItem("cycls_web_search");
    await act(async () => { await result.current.send("again"); });
    expect(bodies[1]).not.toHaveProperty("disabled_tools");
  });
});


describe("watching a run the stream no longer carries (docs/notes/runs.md)", () => {
  test("a stream that ends without [DONE] polls until the run stops running", async () => {
    const polls: string[] = [];
    const fetchMock = vi.fn(async (url: string) => {
      const u = String(url);
      if (u.includes("/chats/")) {
        polls.push(u);
        // No `since` means a FULL load — the server returns the whole chat,
        // never a fragment. The client takes it whole, because its own copy of
        // the cut turn overlaps it.
        return polls.length === 1
          ? { ok: true, status: 200, json: async () => ({
              messages: [{ role: "user", content: "hi" },
                         { role: "assistant", content: "half an answer and the rest", parts: [] }],
              next: 4, open: "assistant", run: "running" }) } as any
          : { ok: true, status: 200, json: async () => ({ messages: [], next: 4, run: "done" }) } as any;
      }
      // a stream that stops mid-answer: no [DONE]
      return {
        ok: true,
        body: { getReader: () => {
          const chunks = ['data: {"type":"chat_id","chat_id":"c1"}\n\n',
                          'data: {"type":"text","text":"half an answer"}\n\n'];
          let i = 0;
          return { read: async () => i < chunks.length
            ? { done: false, value: new TextEncoder().encode(chunks[i++]) }
            : { done: true, value: undefined } };
        } },
      } as any;
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useChat(""));
    await act(async () => { await result.current.send("hi"); });
    await act(async () => { await new Promise((r) => setTimeout(r, 2600)); });

    expect(polls.length).toBeGreaterThanOrEqual(2);
    // the first poll has nothing to resume from and seeds the cursor; every one
    // after that asks only for what is new
    expect(polls[0]).not.toContain("since=");
    expect(polls[1]).toContain("since=4");
    expect(result.current.runStatus).toBe("done");
    // the server's copy replaced the cut one rather than stacking on it
    expect(result.current.messages).toHaveLength(2);
    const last = result.current.messages[result.current.messages.length - 1];
    expect(last.role).toBe("assistant");
    expect(last.content).toBe("half an answer and the rest");
  });

  test("stopping a run does not render the exchange twice", async () => {
    // Nothing advances the cursor during a stream, so a tail poll from the
    // pre-turn index returns the very turn this tab just rendered itself.
    const urls: string[] = [];
    const full = [{ role: "user", content: "first" },
                  { role: "assistant", content: "reply", parts: [] }];
    const after = [...full, { role: "user", content: "ok thanks" },
                   { role: "assistant", content: "you are welcome", parts: [] }];
    const fetchMock = vi.fn(async (url: string) => {
      const u = String(url);
      if (u.includes("/chats/")) {
        urls.push(u);
        if (u.includes("since=")) // the stale-cursor tail that used to duplicate
          return { ok: true, status: 200, json: async () => ({
            messages: after.slice(2), next: 4, open: "assistant", run: "done" }) } as any;
        const first = urls.filter((x) => !x.includes("since=")).length === 1;
        return { ok: true, status: 200, json: async () => ({
          messages: first ? full : after, next: first ? 2 : 4,
          open: "assistant", run: first ? null : "done" }) } as any;
      }
      return { ok: true, body: { getReader: () => {
        const chunks = ['data: {"type":"chat_id","chat_id":"c1"}\n\n',
                        'data: {"type":"text","text":"you are welcome"}\n\n'];
        let i = 0;
        return { read: async () => i < chunks.length
          ? { done: false, value: new TextEncoder().encode(chunks[i++]) }
          : { done: true, value: undefined } };
      } } } as any;
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useChat(""));
    await act(async () => { await result.current.loadChat("c1"); });
    expect(result.current.messages).toHaveLength(2);

    await act(async () => { await result.current.send("ok thanks"); });
    await act(async () => { await new Promise((r) => setTimeout(r, 300)); });

    // four turns, not six: the server's copy replaced this tab's, and the
    // exchange is not on screen twice.
    expect(result.current.messages).toHaveLength(4);
    expect(result.current.messages.filter((m) => m.content === "ok thanks")).toHaveLength(1);
  });
});

describe("a run writes only to the view it started in (docs/notes/runs.md)", () => {
  test("a stream still arriving after a chat switch does not touch the new chat", async () => {
    let open!: () => void;
    const gate = new Promise<void>((r) => { open = r; });
    const fetchMock = vi.fn(async (url: string) => {
      const u = String(url);
      if (u.includes("/chats/other")) {
        // non-empty: an unguarded write lands on THIS bubble
        return { ok: true, status: 200, json: async () => ({
          id: "other", run: null, next: 2,
          messages: [{ role: "user", content: "old question" },
                     { role: "assistant", content: "old answer", parts: [] }],
        }) } as any;
      }
      const chunks = ['data: {"type":"text","text":"from A"}\n\n'];
      let i = 0, parked = false;
      return { ok: true, body: { getReader: () => ({ read: async () => {
        if (i < chunks.length) return { done: false, value: new TextEncoder().encode(chunks[i++]) };
        if (!parked) {
          parked = true;
          await gate;                       // resumes after the user has moved on
          return { done: false, value: new TextEncoder().encode('data: {"type":"text","text":" ...more A"}\n\n') };
        }
        return { done: true, value: undefined };
      } }) } } as any;
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useChat(""));
    let sending!: Promise<void>;
    await act(async () => { sending = result.current.send("hello"); await Promise.resolve(); });
    await act(async () => { await result.current.loadChat("other"); });
    await act(async () => { open(); await sending; });

    const last = result.current.messages[result.current.messages.length - 1];
    expect(last.content).toBe("old answer");   // the final write stayed in chat A
    expect(last.parts).toEqual([]);            // and so did every streamed part
  });
});
