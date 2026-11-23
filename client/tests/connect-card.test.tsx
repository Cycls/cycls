import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { test, expect, afterEach, vi } from "vitest";
import { MessageBubble } from "../src/components/message";
import { ConnectContext } from "../src/components/connect-card";
import type { Connector } from "../src/components/connectors-dialog";

// The connect card stands in the agent's message, as a reload brings it back: the ones that fit, each with its line
// and Connect, one already connected with ✓, and one Not now.

vi.mock("../src/lib/analytics", () => ({ track: vi.fn() }));
afterEach(cleanup);

const dir = [
  { name: "outlook", title: { en: "Outlook" }, description: { en: "Read and send your email" }, connected: false, kind: "oauth" },
  { name: "drive", title: { en: "Google Drive" }, description: { en: "Your files" }, connected: true, kind: "oauth" },
] as unknown as Connector[];

test("the card lists what fits with its line, connects one, and Not now goes on without", () => {
  const connect = vi.fn(), skip = vi.fn();
  render(
    <ConnectContext.Provider value={{ connectors: dir, connect, skip }}>
      <MessageBubble message={{ role: "assistant", content: "", parts: [{ type: "text", text: "I need Outlook to read your inbox." },
        { type: "card", card: { action: "connect", connector: "outlook", connectors: ["outlook", "drive"] }, state: "waiting" }] }} />
    </ConnectContext.Provider>,
  );
  expect(screen.getByText("Read and send your email")).toBeTruthy();
  expect(screen.getByText("Connected")).toBeTruthy();   // Google Drive's, already
  fireEvent.click(screen.getByText("Connect"));
  expect(connect).toHaveBeenCalledWith("outlook");
  fireEvent.click(screen.getByText("Not now"));
  expect(skip).toHaveBeenCalledWith(["outlook", "drive"]);
});
