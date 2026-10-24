import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { ApprovalCard, ApprovalContext, matchAction, type Confirm } from "../src/components/approval-card";
import { ConnectorsContext } from "../src/components/parts/tool-call";
import type { Connector } from "../src/components/connectors-dialog";
import type { Part } from "../src/hooks/use-chat";

// The question a gated call asks, in the conversation: the action in plain words (the CMS's for a connector),
// the face of its step, "Don't ask again" (Always allow) except for a delete, and a receipt once answered.

const outlook = {
  name: "outlook", title: { en: "Outlook" }, icon: "https://cdn/outlook.svg",
  actions: [{ match: "POST me/sendMail", ask: { en: "Send this email?" }, who: { en: "{agent} will send it from your Outlook, as you." },
              button: { en: "Send" }, done: { en: "Sent to {to}" },
              show: [{ id: "to", label: { en: "To" }, from: "body.message.toRecipients" }, { label: { en: "Subject" }, from: "body.message.subject" }] }],
} as unknown as Connector;
const send: Confirm = { tool: "outlook_request", key: "k1", label: "outlook · request", connector: "outlook", risk: "write",
  args: { method: "POST", path: "me/sendMail", context: "Sending Sara the Q3 numbers",
          body: JSON.stringify({ message: { subject: "Q3 numbers", toRecipients: [{ emailAddress: { address: "sara@acme.com" } }] } }) } };

function show(card: Confirm, state = "waiting", busy = false) {
  const answer = vi.fn();
  render(
    <ConnectorsContext.Provider value={[outlook]}>
      <ApprovalContext.Provider value={{ agent: "Super", answer, busy }}>
        <ApprovalCard part={{ type: "card", card: card as unknown as Part["card"], state }} />
      </ApprovalContext.Provider>
    </ConnectorsContext.Provider>);
  return answer;
}

describe("the approval card", () => {
  afterEach(cleanup);

  it("words a connector call from the CMS and answers with its title", () => {
    const answer = show(send);
    expect(screen.getByText("Send this email?")).toBeTruthy();
    expect(screen.getByText("Super will send it from your Outlook, as you.")).toBeTruthy();
    expect(screen.getByText("sara@acme.com")).toBeTruthy();
    expect(screen.getByText("Q3 numbers")).toBeTruthy();
    fireEvent.click(screen.getByText("Don't ask again for Outlook"));
    fireEvent.click(screen.getByText("Send"));
    expect(answer).toHaveBeenCalledWith(send, true, true, "Send this email?");
  });

  it("falls back to plain words and the agent's own line when the CMS has none", () => {
    const answer = show({ ...send, args: { ...send.args, path: "me/calendar/events" } });
    expect(screen.getByText("Let Super make a change in Outlook?")).toBeTruthy();
    expect(screen.getByText("Sending Sara the Q3 numbers")).toBeTruthy();
    fireEvent.click(screen.getByText("Not now"));
    expect(answer).toHaveBeenCalledWith(expect.objectContaining({ key: "k1" }), false, false, "Let Super make a change in Outlook?");
  });

  it("never offers \"Don't ask again\" for a delete", () => {
    show({ ...send, risk: "destructive", args: { method: "DELETE", path: "me/messages/1" } });
    expect(screen.getByText("Let Super delete something in Outlook?")).toBeTruthy();
    expect(screen.getByText("This can't be undone.")).toBeTruthy();
    expect(screen.queryByText(/Don't ask again/)).toBeNull();
    expect(screen.getByText("Delete").className).toContain("bg-destructive");
  });

  it("words the built-in tools in the app's own strings", () => {
    show({ tool: "bash", key: "k2", label: "Bash · mkdir out", tool_name: "Bash", step: "mkdir out", risk: "write", args: { command: "mkdir out" } });
    expect(screen.getByText("Make changes in your workspace?")).toBeTruthy();
    expect(screen.getByText("mkdir out")).toBeTruthy();
    expect(screen.getByText("Don't ask again for commands")).toBeTruthy();
    cleanup();
    show({ tool: "edit", key: "k3", label: "Editing · main.py", tool_name: "Editing", step: "main.py", risk: "write",
           args: { path: "scripts/main.py", old_str: "a", new_str: "b" } });
    expect(screen.getByText("Change main.py?")).toBeTruthy();
    expect(screen.getByText("py")).toBeTruthy();   // the file's own tile
  });

  it("turns into its receipt once answered", () => {
    const cases: [string, boolean, RegExp][] = [
      ["done", false, /Sent to sara@acme.com/], ["approved", true, /Working on it/], ["approved", false, /Approved/],
      ["failed", false, /Didn't go through/], ["declined", false, /Not now/], ["skipped", false, /Skipped/]];
    for (const [state, busy, text] of cases) {
      show(send, state, busy);
      expect(screen.getByText(text)).toBeTruthy();
      expect(screen.queryByText("Send")).toBeNull();
      cleanup();
    }
  });
});

describe("the approval card on a shared chat", () => {
  afterEach(cleanup);
  it("shows the question as a receipt: nobody there can answer it", () => {
    render(<ApprovalCard part={{ type: "card", card: send as unknown as Part["card"], state: "waiting" }} />);
    expect(screen.getByText("Waiting for an answer")).toBeTruthy();
    expect(screen.queryByText("Not now")).toBeNull();
  });
});

describe("matching a CMS action", () => {
  it("reads * as one path segment and ignores the query", () => {
    const actions = [{ match: "DELETE me/events/*", ask: { en: "Cancel this event?" } }];
    const card = (method: string, path: string): Confirm => ({ tool: "outlook_request", key: "k", label: "", args: { method, path } });
    expect(matchAction(card("DELETE", "/me/events/AAMk1?x=1"), actions)?.ask.en).toBe("Cancel this event?");
    expect(matchAction(card("DELETE", "me/events/AAMk1/attachments/2"), actions)).toBeUndefined();
    expect(matchAction(card("POST", "me/events/AAMk1"), actions)).toBeUndefined();
  });
});
