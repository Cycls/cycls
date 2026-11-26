import { describe, it, expect, afterEach, vi } from "vitest";
import { render, cleanup, fireEvent } from "@testing-library/react";
import { FlowBlock, flowOf } from "../src/components/parts/flow-chart";
import { FileActions } from "../src/components/parts/file-part";
import { TextPart } from "../src/components/parts/text-part";

// A flowchart in a reply: a ```flowchart block of JSON laid out and drawn here, with no library.

afterEach(cleanup);
const refund = {
  title: "Refund", nodes: [
    { id: "a", label: "Request arrives", shape: "start" }, { id: "b", label: "Within 14 days?", shape: "decision" },
    { id: "c", label: "Refund", shape: "end" }, { id: "d", label: "Ask for a receipt" }, { id: "x", label: "Unrelated note", shape: "note" },
  ],
  edges: [{ from: "a", to: "b" }, { from: "b", to: "c", label: "Yes" }, { from: "b", to: "d", label: "No" }, { from: "d", to: "b" }, { from: "a", to: "ghost" }],
};
const at = (g: Element) => (g.getAttribute("style") || "").match(/translate\(([-\d.]+)px, ([-\d.]+)px\)/)!.slice(1).map(Number);

describe("a flowchart in a reply", () => {
  it("is made safe to draw: known shapes, arrows only between its steps", () => {
    const f = flowOf({ ...refund, nodes: [...refund.nodes, { id: "a", label: "twice" }, { label: "no id" }, { id: 7, shape: "hexagon" }] })!;
    expect(f.nodes.map((n) => n.id)).toEqual(["a", "b", "c", "d", "x", "7"]);
    expect(f.nodes[5].shape).toBe("step");
    expect(f.edges).toHaveLength(4);
    expect(flowOf({ nodes: [] })).toBeNull();
  });

  it("lays its steps out down the page, the loop back included, and draws an arrow for each", () => {
    const { container, getByText } = render(<FlowBlock code={JSON.stringify(refund)} done />);
    const steps = [...container.querySelectorAll("g.flow-move.cursor-pointer")];
    expect(steps).toHaveLength(5);
    const y = Object.fromEntries(refund.nodes.map((n, i) => [n.id, at(steps[i])[1]]));
    expect(y.a).toBeLessThan(y.b);
    expect(y.b).toBeLessThan(y.c);
    expect(y.b).toBeLessThan(y.d);   // the way back from d to b doesn't pull b under d
    expect(container.querySelectorAll("path.chart-draw")).toHaveLength(4);
    expect(getByText("Yes")).toBeTruthy();
  });

  it("lights the path through a step under the pointer, and turns to run across", () => {
    const { container, getByLabelText } = render(<FlowBlock code={JSON.stringify(refund)} done />);
    const steps = [...container.querySelectorAll("g.flow-move.cursor-pointer")];
    fireEvent.pointerEnter(steps[2]);   // Refund: a, b and c are its path; the note isn't
    expect((steps[0] as HTMLElement).style.opacity).toBe("1");
    expect((steps[4] as HTMLElement).style.opacity).toBe("0.3");
    fireEvent.pointerLeave(steps[2]);
    const before = at(steps[2]);
    fireEvent.click(getByLabelText("Side to side"));
    const after = at([...container.querySelectorAll("g.flow-move.cursor-pointer")][2]);
    expect(after).not.toEqual(before);
  });

  it("goes to the person's files as a flowchart block", () => {
    const save = vi.fn();
    const { getByLabelText, getByText } = render(
      <FileActions.Provider value={{ download: () => {}, save }}><FlowBlock code={JSON.stringify(refund)} done /></FileActions.Provider>);
    fireEvent.click(getByLabelText("Download"));
    fireEvent.click(getByText("Save to files"));
    expect(save.mock.calls[0][0]).toBe("diagrams/Refund.md");
    expect(save.mock.calls[0][1]).toMatch(/^```flowchart\n/);
  });

  it("is drawn from a reply's fenced block, and waits while it streams", () => {
    const { getByRole } = render(<TextPart text={"Here:\n\n```flowchart\n" + JSON.stringify(refund) + "\n```\n"} />);
    expect(getByRole("img").getAttribute("aria-label")).toBe("Refund");
    cleanup();
    const { container } = render(<FlowBlock code={JSON.stringify(refund).slice(0, 30)} done={false} />);
    expect(container.querySelector(".animate-pulse")).toBeTruthy();
  });
});
