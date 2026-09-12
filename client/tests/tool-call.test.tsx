import { describe, it, expect, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { ToolCall, ConnectorsContext } from "../src/components/parts/tool-call";
import type { Connector } from "../src/components/connectors-dialog";

const google = { name: "google", title: "Google Drive", connected: true } as unknown as Connector;
const part = { type: "step", id: "t1", tool_name: "drive · search_files", step: "Q3 decks", connector: "google", args: '{"q":"Q3"}', result: "3 files" };

describe("ToolCall", () => {
  afterEach(cleanup);
  it("collapsed by default; a tap shows the request pretty-printed and the response", () => {
    render(<ConnectorsContext.Provider value={[google]}><ToolCall p={part} /></ConnectorsContext.Provider>);
    expect(screen.getByText("Search files")).toBeTruthy();
    expect(screen.queryByText("Request")).toBeNull();
    fireEvent.click(screen.getByText("Search files"));
    expect(screen.getByText("Request")).toBeTruthy();
    expect(screen.getByText((s) => s.includes('"q": "Q3"'))).toBeTruthy();
    expect(screen.getByText("3 files")).toBeTruthy();
  });
  it("a connector with no logo still gets a face", () => {
    const { container } = render(<ToolCall p={part} />);
    expect(container.querySelector("svg")).toBeTruthy();
  });
});

describe("ToolCall — a web search", () => {
  afterEach(cleanup);
  const search = {
    type: "step", id: "s1", tool_name: "Web Search", step: "riyadh metro line 1",
    sources: [{ title: "Line 1 opens", url: "https://spa.gov.sa/a", snippet: "" },
              { title: "Ridership climbs", url: "https://www.argaam.com/b", snippet: "" }],
  };
  it("counts its results on the row and lists them with their domains when opened", () => {
    render(<ToolCall p={search} />);
    expect(screen.getByText("riyadh metro line 1")).toBeTruthy();
    expect(screen.getByText("2 results")).toBeTruthy();
    expect(screen.queryByText("Line 1 opens")).toBeNull();
    fireEvent.click(screen.getByText("riyadh metro line 1"));
    expect(screen.getByText("Line 1 opens")).toBeTruthy();
    expect(screen.getByText("argaam.com")).toBeTruthy();            // www. stripped
    expect(screen.getAllByRole("link")[0].getAttribute("href")).toBe("https://spa.gov.sa/a");
  });
  it("a failed call says so instead of counting results", () => {
    render(<ToolCall p={{ ...search, ok: false }} />);
    expect(screen.getByText("Failed")).toBeTruthy();
    expect(screen.queryByText("2 results")).toBeNull();
  });
});

describe("ToolCall — a custom tool", () => {
  afterEach(cleanup);
  it("wears the icon the SDK gave it, with no connector in sight", () => {
    const p = { type: "step", id: "t1", tool_name: "legal_search", step: "zakat",
                icon: "https://moj.gov.sa/icon.svg", args: '{"query":"zakat"}', result: "3 rows" };
    const { container } = render(<ToolCall p={p} />);
    expect(container.querySelector('img[src="https://moj.gov.sa/icon.svg"]')).toBeTruthy();
    fireEvent.click(screen.getByText("Legal search"));
    expect(screen.getByText("3 rows")).toBeTruthy();
  });
});
