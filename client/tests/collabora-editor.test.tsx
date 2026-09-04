/**
 * CollaboraEditor — fetches the WOPI editor URL and embeds it via a token
 * form-POST; falls back to a download card when the editor is unavailable.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { describe, test, expect, vi, beforeAll } from "vitest";
import { CollaboraEditor } from "../src/components/collabora-editor";

// jsdom doesn't implement real form submission; stub it so the component's
// auto-submit is observable and doesn't throw.
beforeAll(() => {
  vi.spyOn(HTMLFormElement.prototype, "submit").mockImplementation(() => {});
});

const CFG = {
  editor_url: "https://collabora.cycls.ai/browser/abc/cool.html?WOPISrc=x",
  access_token: "tok123",
  access_token_ttl: 999,
};

describe("CollaboraEditor", () => {
  test("fetches the editor for the file and embeds it via a token form-POST", async () => {
    const getEditor = vi.fn().mockResolvedValue(CFG);
    const { container } = render(
      <CollaboraEditor file={{ path: "a/deck.pptx", name: "deck.pptx" }} getEditor={getEditor} />,
    );

    expect(getEditor).toHaveBeenCalledWith("a/deck.pptx");   // asks the server for THIS file

    await waitFor(() => {
      const form = container.querySelector("form")!;
      expect(form).toBeTruthy();
      expect(form.getAttribute("action")).toBe(CFG.editor_url);       // posts to Collabora
      expect(form.getAttribute("target")).toBe("cycls-collabora");    // into the named iframe
      const token = form.querySelector('input[name="access_token"]') as HTMLInputElement;
      expect(token.value).toBe("tok123");                             // token in the body, not the URL
    });
    expect(container.querySelector('iframe[name="cycls-collabora"]')).toBeTruthy();
    expect(HTMLFormElement.prototype.submit).toHaveBeenCalled();      // auto-submitted on load
  });

  test("falls back to a download action when the editor is unavailable", async () => {
    const getEditor = vi.fn().mockRejectedValue(new Error("503"));
    const onDownload = vi.fn();
    render(
      <CollaboraEditor file={{ path: "d.docx", name: "d.docx" }} getEditor={getEditor} onDownload={onDownload} />,
    );
    const btn = await screen.findByRole("button");   // the download button on the error card
    btn.click();
    expect(onDownload).toHaveBeenCalled();
  });
});
