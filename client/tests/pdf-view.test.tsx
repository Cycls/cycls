import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { CanvasDoc } from "../src/components/canvas";

vi.mock("../src/lib/analytics", () => ({ track: vi.fn() }));

describe("a PDF in the canvas", () => {
  afterEach(() => {
    cleanup();
    delete (navigator as { pdfViewerEnabled?: boolean }).pdfViewerEnabled;
  });

  it("is the browser's own viewer where it has one, and its card with Open where it has none (Chrome on Android)", () => {
    const file = { path: "reports/q3-report.pdf", name: "q3-report.pdf" };
    const first = render(<CanvasDoc file={file} content="blob:https://super.example/5f1c" error={false} />);
    expect(first.container.querySelector("iframe")).toBeTruthy();
    first.unmount();

    Object.defineProperty(navigator, "pdfViewerEnabled", { value: false, configurable: true });
    const { container } = render(<CanvasDoc file={file} content="blob:https://super.example/5f1c" error={false} />);
    expect(container.querySelector("iframe")).toBeNull();   // no blob address in the browser's placeholder
    expect(screen.getByText(/q3-report/)).toBeTruthy();
    expect(screen.getByText("Open in new tab").closest("a")?.getAttribute("href")).toBe("blob:https://super.example/5f1c");
  });
});
