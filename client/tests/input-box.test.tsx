import { describe, it, expect, vi, afterEach } from "vitest";
import { useRef, useState } from "react";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import { InputBox } from "../src/components/input-box";
import type { Connector } from "../src/components/connectors-dialog";

vi.mock("../src/lib/analytics", () => ({ track: vi.fn() }));

const drive = { name: "google", title: "Google Drive", connected: true, allowed: true } as unknown as Connector;

function Harness({ onAddConnector }: { onAddConnector: (c: Connector) => void }) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const [input, setInput] = useState("");
  return (
    <InputBox
      textareaRef={ref} input={input} setInput={setInput}
      handleKeyDown={() => {}} handleSubmit={() => {}} isStreaming={false} onStop={() => {}}
      listening={false} transcribing={false} startMic={() => {}} stopMic={() => {}} cancelMic={() => {}}
      onMentionSearch={async () => [{ name: "Google Drive", path: "", connector: drive }]}
      onAddConnector={onAddConnector}
    />
  );
}

describe("the composer's @ pill", () => {
  afterEach(cleanup);
  it("puts the connector's token in the line, not in a row above it", async () => {
    const onAddConnector = vi.fn();
    render(<Harness onAddConnector={onAddConnector} />);
    const box = screen.getByRole("textbox") as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: "check @dri" } });
    const row = await screen.findByText("Google Drive");
    fireEvent.mouseDown(row);   // the picker commits on mousedown, before the textarea loses focus
    await waitFor(() => expect(box.value).toBe("check @Google Drive "));
    expect(onAddConnector).toHaveBeenCalledWith(drive);
  });
});

describe("the @ picker after a deletion", () => {
  afterEach(cleanup);
  it("offers the connector again once its token is gone from the line", async () => {
    // The composer's own filter is the input text, so a search run twice with the token deleted
    // in between must hit the connector both times.
    const connectors = [drive];
    let text = "";
    const search = async (q: string) => connectors
      .filter((c) => !text.includes(`@${c.title}`) && c.title!.toLowerCase().includes(q.toLowerCase()))
      .map((c) => ({ name: c.title!, path: "", connector: c }));
    expect((await search("goo")).length).toBe(1);
    text = "check @Google Drive ";
    expect((await search("goo")).length).toBe(0);      // already in the line
    text = "check ";
    expect((await search("goo")).length).toBe(1);      // deleted → offered again
  });
});
