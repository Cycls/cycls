import { describe, it, expect, vi, afterEach } from "vitest";
import { useRef, useState } from "react";
import { render, screen, fireEvent, cleanup, act } from "@testing-library/react";
import { InputBox } from "../src/components/input-box";
import { useHeldSend, uploading } from "../src/hooks/use-held-send";
import type { Attachment, SendExtra } from "../src/hooks/use-chat";

vi.mock("../src/lib/analytics", () => ({ track: vi.fn() }));

// A send pressed while a file was still uploading did nothing, and nothing said why. Now it is
// held, shown, and sent by itself when the uploads finish.

const HINT = "Sends when the upload finishes";
const video = (status?: Attachment["status"], url = "blob:video"): Attachment =>
  ({ name: "clip.mp4", size: 8_500_000, type: "video/mp4", url, status });

// The composer wired the way Chat wires it: the same guard in the submit, Enter to send,
// Escape and removing a file to take a held send back.
const ctl = {} as {
  setAttachments: (f: (prev: Attachment[]) => Attachment[]) => void;
  submit: (overrideText?: string, origin?: string) => void;
};
function Composer({ initial, onSend }: {
  initial: Attachment[];
  onSend: (text: string, attachments: Attachment[], origin: string, extra?: SendExtra) => void;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState(initial);
  const submitRef = useRef<(o?: string, origin?: string, extra?: SendExtra) => void>(() => {});
  const { held, request, cancel } = useHeldSend({
    input, attachments, send: (origin, extra) => submitRef.current(undefined, origin, extra),
  });
  const handleSubmit = (overrideText?: string, origin = "keyboard", extra?: SendExtra) => {
    const text = (overrideText ?? input).trim();
    if (!text) return;
    if (uploading(attachments)) {
      if (overrideText !== undefined) setInput(text);
      request(text, origin, extra);
      return;
    }
    onSend(text, attachments, origin, extra);
    setInput("");
    setAttachments([]);
  };
  submitRef.current = handleSubmit;
  ctl.setAttachments = setAttachments;
  ctl.submit = handleSubmit;
  return (
    <InputBox
      textareaRef={ref} input={input} setInput={setInput}
      handleKeyDown={(e) => {
        if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSubmit(); }
        if (e.key === "Escape" && held) { e.preventDefault(); cancel(); }
      }}
      handleSubmit={handleSubmit} isStreaming={false} onStop={() => {}}
      attachments={attachments}
      onRemoveFile={(i) => { cancel(); setAttachments((prev) => prev.filter((_, j) => j !== i)); }}
      held={held} onCancelHeld={cancel}
      listening={false} transcribing={false} startMic={() => {}} stopMic={() => {}} cancelMic={() => {}}
    />
  );
}

const box = () => screen.getByRole("textbox") as HTMLTextAreaElement;
const type = (text: string) => fireEvent.change(box(), { target: { value: text } });
const enter = () => fireEvent.keyDown(box(), { key: "Enter" });
const finish = (url = "blob:video", status?: Attachment["status"]) =>
  act(() => ctl.setAttachments((prev) => prev.map((a) =>
    a.url === url ? { ...a, status, path: status ? undefined : `attachments/${a.name}` } : a)));

afterEach(cleanup);

describe("a send pressed while a file uploads", () => {
  it("is held, says so, and goes when the upload finishes", () => {
    const onSend = vi.fn();
    render(<Composer initial={[video("uploading")]} onSend={onSend} />);
    type("cut this down to 30 seconds");
    enter();
    expect(onSend).not.toHaveBeenCalled();
    expect(screen.getByTestId("held-send").textContent).toContain(HINT);
    expect(screen.getByLabelText(HINT)).toBeTruthy();   // the send button, held
    finish();
    expect(onSend).toHaveBeenCalledOnce();
    const [text, attachments, origin] = onSend.mock.calls[0];
    expect(text).toBe("cut this down to 30 seconds");
    expect(attachments).toEqual([{ ...video(), path: "attachments/clip.mp4" }]);
    expect(origin).toBe("keyboard");
    expect(screen.queryByTestId("held-send")).toBeNull();
    expect(box().value).toBe("");
  });

  it("is held from the send button too, which stays pressable while the file uploads", () => {
    const onSend = vi.fn();
    render(<Composer initial={[video("uploading")]} onSend={onSend} />);
    type("hello");
    const send = screen.getByLabelText("Send") as HTMLButtonElement;
    expect(send.disabled).toBe(false);
    fireEvent.click(send);
    expect(screen.getByTestId("held-send")).toBeTruthy();
    finish();
    expect(onSend).toHaveBeenCalledOnce();
  });

  it("is dropped when the upload fails, and the text stays", () => {
    const onSend = vi.fn();
    render(<Composer initial={[video("uploading")]} onSend={onSend} />);
    type("hello");
    enter();
    finish("blob:video", "error");
    expect(onSend).not.toHaveBeenCalled();
    expect(screen.queryByTestId("held-send")).toBeNull();
    expect(screen.getByText("Upload failed")).toBeTruthy();   // the chip's own failure line
    expect(box().value).toBe("hello");
  });

  it("is taken back by editing the text", () => {
    const onSend = vi.fn();
    render(<Composer initial={[video("uploading")]} onSend={onSend} />);
    type("hello");
    enter();
    type("hello there");
    expect(screen.queryByTestId("held-send")).toBeNull();
    finish();
    expect(onSend).not.toHaveBeenCalled();
    expect(box().value).toBe("hello there");
  });

  it("is taken back by Escape, by Cancel, and by removing a file", () => {
    const onSend = vi.fn();
    render(<Composer initial={[video("uploading")]} onSend={onSend} />);
    type("hello");
    enter();
    fireEvent.keyDown(box(), { key: "Escape" });
    expect(screen.queryByTestId("held-send")).toBeNull();
    enter();
    fireEvent.click(screen.getByText("Cancel"));
    expect(screen.queryByTestId("held-send")).toBeNull();
    enter();
    fireEvent.click(screen.getByLabelText("Remove file"));
    expect(screen.queryByTestId("held-send")).toBeNull();
    expect(onSend).not.toHaveBeenCalled();
  });

  it("goes once, however many times send is pressed while held", () => {
    const onSend = vi.fn();
    render(<Composer initial={[video("uploading")]} onSend={onSend} />);
    type("hello");
    enter();
    enter();
    fireEvent.click(screen.getByLabelText(HINT));
    expect(screen.getByTestId("held-send")).toBeTruthy();
    finish();
    finish();
    act(() => ctl.setAttachments((prev) => [...prev]));
    expect(onSend).toHaveBeenCalledOnce();
  });

  it("waits for a file added while held, then sends it too", () => {
    const onSend = vi.fn();
    render(<Composer initial={[video("uploading")]} onSend={onSend} />);
    type("hello");
    enter();
    act(() => ctl.setAttachments((prev) => [...prev, video("uploading", "blob:second")]));
    finish();
    expect(onSend).not.toHaveBeenCalled();
    expect(screen.getByTestId("held-send")).toBeTruthy();
    finish("blob:second");
    expect(onSend).toHaveBeenCalledOnce();
    expect(onSend.mock.calls[0][1]).toHaveLength(2);
  });

  it("is not stopped by a file that had already failed before send was pressed", () => {
    const onSend = vi.fn();
    render(<Composer initial={[video("error", "blob:old"), video("uploading")]} onSend={onSend} />);
    type("hello");
    enter();
    finish();
    expect(onSend).toHaveBeenCalledOnce();
  });

  it("keeps a spoken message in the composer while it waits, and sends it as voice", () => {
    const onSend = vi.fn();
    render(<Composer initial={[video("uploading")]} onSend={onSend} />);
    act(() => ctl.submit("make it shorter", "voice"));
    expect(box().value).toBe("make it shorter");
    expect(screen.getByTestId("held-send")).toBeTruthy();
    finish();
    expect(onSend).toHaveBeenCalledOnce();
    expect(onSend.mock.calls[0][0]).toBe("make it shorter");
    expect(onSend.mock.calls[0][2]).toBe("voice");
  });

  it("with nothing uploading, sends at once", () => {
    const onSend = vi.fn();
    render(<Composer initial={[]} onSend={onSend} />);
    type("hello");
    enter();
    expect(onSend).toHaveBeenCalledOnce();
    expect(screen.queryByTestId("held-send")).toBeNull();
  });
});
