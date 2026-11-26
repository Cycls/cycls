import { describe, it, expect, afterEach, vi } from "vitest";
import { render, cleanup, fireEvent, waitFor } from "@testing-library/react";
import { SearchDialog } from "../src/components/search-dialog";

// Search across the workspaces: each hit says where it lives, workspace / folder, and a workspace can be picked.

afterEach(cleanup);
Element.prototype.scrollIntoView ??= () => {};   // jsdom has none
const files = [{ name: "budget.xlsx", path: "finance/budget.xlsx", ws: "u-me" }, { name: "budget.xlsx", path: "forecasts/budget.xlsx", ws: "t-sales" }];
const everywhere = vi.fn(async (_q: string, ws?: string) => ({
  workspaces: [{ id: "u-me", name: "Personal" }, { id: "t-sales", name: "Sales", icon: "📈" }],
  chats: [], apps: [], files: files.filter((f) => !ws || f.ws === ws),
}));

describe("search across the workspaces", () => {
  it("names each hit's workspace and folder, and keeps to the workspace picked", async () => {
    const { findByText, getByText, getByRole, queryByText } = render(<SearchDialog everywhere={everywhere} here="u-me" onOpen={() => {}} onClose={() => {}} />);
    expect(await findByText("forecasts")).toBeTruthy();
    expect(getByText("Sales")).toBeTruthy();
    expect(getByText("Personal")).toBeTruthy();
    fireEvent.click(getByRole("button", { name: "Workspaces" }));
    expect(getByText("You're here")).toBeTruthy();
    fireEvent.click(getByRole("button", { name: "📈 Sales" }));
    await waitFor(() => expect(everywhere).toHaveBeenLastCalledWith("", "t-sales"));
    expect(queryByText("finance")).toBeNull();
    expect(getByText("forecasts")).toBeTruthy();
    expect(getByRole("button", { name: "Workspaces" }).textContent).toContain("Sales");
  });
});
