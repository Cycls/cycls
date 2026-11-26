import { describe, it, expect, afterEach, vi } from "vitest";
import { render, cleanup, fireEvent } from "@testing-library/react";
import { ChartBlock, chartOf } from "../src/components/parts/data-chart";
import { TextPart } from "../src/components/parts/text-part";
import { FileActions } from "../src/components/parts/file-part";
import { csv } from "../src/components/parts/export";

// A chart in a reply: a ```chart block of JSON drawn in SVG, in the Design tool's format, with no library.

afterEach(cleanup);
if (!window.PointerEvent) (window as unknown as { PointerEvent: typeof MouseEvent }).PointerEvent = MouseEvent;   // jsdom has none
const sales = { kind: "column", title: "Sales", data: { labels: ["Jan", "Feb", "Mar"], series: [{ name: "Riyadh", values: [120, 150, 90] }, { name: "Jeddah", values: [80, 95, 110] }] } };

describe("a chart in a reply", () => {
  it("is made safe to draw: numbers, hex colors, a kind it knows", () => {
    const c = chartOf({ kind: "radar", data: { labels: ["a", "b"], series: [{ name: "x", values: [1, "two"], color: "red;}" }] } })!;
    expect(c.kind).toBe("column");
    expect(c.series[0].values).toEqual([1, 0]);
    expect(c.series[0].color).toMatch(/^#/);
    expect(chartOf({ data: { labels: [], series: [] } })).toBeNull();
    expect(chartOf("nonsense")).toBeNull();
  });

  it("draws a bar for each label of each series, a legend, and the values under the pointer", () => {
    const { container, getByText, getByRole } = render(<ChartBlock code={JSON.stringify(sales)} done />);
    expect(container.querySelectorAll("path.chart-rise")).toHaveLength(6);
    expect(getByText("Sales")).toBeTruthy();
    expect(getByText("Jeddah")).toBeTruthy();
    const svg = getByRole("img");
    svg.getBoundingClientRect = () => ({ left: 0, top: 0, width: 480, height: 220 } as DOMRect);
    fireEvent.pointerMove(svg, { clientX: 470, clientY: 100 });
    expect(getByText("110")).toBeTruthy();
  });

  it("draws lines, areas, rows, a pie and a donut with its total", () => {
    for (const kind of ["line", "area", "bar", "stacked", "pie"]) {
      const { getByRole } = render(<ChartBlock code={JSON.stringify({ ...sales, kind })} done />);
      expect(getByRole("img").querySelectorAll("path").length).toBeGreaterThan(0);
      cleanup();
    }
    const { getByText } = render(<ChartBlock code={JSON.stringify({ ...sales, kind: "donut", short: true, prefix: "SAR " })} done />);
    expect(getByText("SAR 360")).toBeTruthy();
  });

  it("is drawn another way, as a table, with a series put away, or over its last few labels", () => {
    const { container, getByLabelText, getByText, queryByText } = render(<ChartBlock code={JSON.stringify(sales)} done />);
    fireEvent.click(getByLabelText("Line"));
    expect(container.querySelectorAll("path.chart-rise")).toHaveLength(0);
    expect(container.querySelectorAll("path.chart-draw")).toHaveLength(2);
    fireEvent.click(getByText("Jeddah"));
    expect(container.querySelectorAll("path.chart-draw")).toHaveLength(1);
    fireEvent.click(getByLabelText("Table"));
    expect(container.querySelectorAll("tbody tr")).toHaveLength(3);
    expect(getByText("Total")).toBeTruthy();
    expect(queryByText("Jeddah", { selector: "th bdi" })).toBeNull();
    cleanup();

    const long = { kind: "line", data: { labels: Array.from({ length: 40 }, (_, i) => `D${i}`), series: [{ name: "Gold", values: Array.from({ length: 40 }, (_, i) => 100 + i) }] } };
    const r = render(<ChartBlock code={JSON.stringify(long)} done />);
    fireEvent.click(r.getByText("Last 12"));
    fireEvent.click(r.getByLabelText("Table"));
    expect(r.container.querySelectorAll("tbody tr")).toHaveLength(12);
  });

  it("puts a donut's slice away from its legend, and its total follows", () => {
    const { getByText } = render(<ChartBlock code={JSON.stringify({ ...sales, kind: "donut" })} done />);
    expect(getByText("360")).toBeTruthy();
    fireEvent.click(getByText("Jan"));
    expect(getByText("240")).toBeTruthy();
  });

  it("draws a treemap of boxes sized by their value, and turns into a donut", () => {
    const { container, getByLabelText, getByText } = render(<ChartBlock code={JSON.stringify({ ...sales, kind: "treemap" })} done />);
    const tiles = [...container.querySelectorAll("svg[role=img] rect")].map((r) => Number(r.getAttribute("width")) * Number(r.getAttribute("height")));
    expect(tiles).toHaveLength(3);
    expect(tiles[0]).toBeGreaterThan(tiles[2]);   // Feb, the biggest, first
    fireEvent.click(getByLabelText("Donut"));
    expect(getByText("360")).toBeTruthy();
  });

  it("goes to the person's files as a chart block, and its numbers as a CSV Excel reads in Arabic", async () => {
    const save = vi.fn();
    const { getByLabelText, getByText } = render(
      <FileActions.Provider value={{ download: () => {}, save }}><ChartBlock code={JSON.stringify(sales)} done /></FileActions.Provider>);
    fireEvent.click(getByLabelText("Line"));
    fireEvent.click(getByLabelText("Download"));
    fireEvent.click(getByText("Save to files"));
    const [path, body] = save.mock.calls[0];
    expect(path).toBe("charts/Sales.md");
    expect(JSON.parse(body.replace(/^```chart\n|\n```\n$/g, ""))).toMatchObject({ kind: "line", title: "Sales", data: { labels: ["Jan", "Feb", "Mar"] } });
    const bytes = new Uint8Array(await new Promise<ArrayBuffer>((ok) => {
      const r = new FileReader(); r.onload = () => ok(r.result as ArrayBuffer); r.readAsArrayBuffer(csv([["", "الرياض"], ["Jan", 120], ["a,b", 1]]));
    }));
    expect([...bytes.slice(0, 3)]).toEqual([0xef, 0xbb, 0xbf]);   // the mark that tells Excel it's UTF-8
    expect(new TextDecoder().decode(bytes.slice(3))).toBe(',الرياض\r\nJan,120\r\n"a,b",1');
  });

  it("waits while its JSON streams, and shows the JSON when it never becomes a chart", () => {
    const half = JSON.stringify(sales).slice(0, 40);
    const { container, rerender, queryByRole } = render(<ChartBlock code={half} done={false} />);
    expect(container.querySelector(".animate-pulse")).toBeTruthy();
    rerender(<ChartBlock code={half} done />);
    expect(queryByRole("img")).toBeNull();
    expect(container.textContent).toContain('"kind"');
  });

  it("is drawn from a reply's fenced block", () => {
    const { getByRole } = render(<TextPart text={"Here it is:\n\n```chart\n" + JSON.stringify(sales) + "\n```\n"} />);
    expect(getByRole("img").getAttribute("aria-label")).toBe("Sales");
  });
});
