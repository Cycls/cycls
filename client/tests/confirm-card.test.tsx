import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { ConfirmCard } from "../src/components/confirm-card";

describe("ConfirmCard", () => {
  afterEach(cleanup);
  it("offers approve, always allow and cancel, each to its own handler", () => {
    const onApprove = vi.fn(), onAlways = vi.fn(), onDismiss = vi.fn();
    render(<ConfirmCard label="drive · delete_file" args={{ name: "q3.xlsx" }} onApprove={onApprove} onAlways={onAlways} onDismiss={onDismiss} />);
    expect(screen.getByText("drive · delete_file needs your approval")).toBeTruthy();
    expect(screen.getByText("name: q3.xlsx")).toBeTruthy();
    fireEvent.click(screen.getByText("Always allow"));
    fireEvent.click(screen.getByText("Approve"));
    fireEvent.click(screen.getByText("Cancel"));
    expect([onAlways, onApprove, onDismiss].map((f) => f.mock.calls.length)).toEqual([1, 1, 1]);
  });
});

describe("ConfirmCard — a builtin", () => {
  afterEach(cleanup);
  it("offers Always allow too — a builtin's choice has its own store", () => {
    const onAlways = vi.fn();
    render(<ConfirmCard label="Bash · rm -rf build" args={{ command: "rm -rf build" }}
                        onApprove={() => {}} onAlways={onAlways} onDismiss={() => {}} />);
    expect(screen.getByText("Bash · rm -rf build needs your approval")).toBeTruthy();
    fireEvent.click(screen.getByText("Always allow"));
    expect(onAlways).toHaveBeenCalledOnce();
  });
});
