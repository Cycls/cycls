import { describe, it, expect, vi } from "vitest";
import { renderHook } from "@testing-library/react";
import { useAllPages, complete } from "../src/hooks/use-all-pages";
import { nameIn, findIn, type WorkspacesMenu } from "../src/components/workspace-switcher";

// Clerk returns 10 members a page and stops there unless asked: a team past ten lost members from every list,
// and their names turned into user ids.

describe("every page of a Clerk list", () => {
  it("keeps asking for the next page until there is none", () => {
    const fetchNext = vi.fn();
    const page = (hasNextPage: boolean, isFetching: boolean) => ({ hasNextPage, isFetching, isLoading: false, fetchNext });
    const { rerender } = renderHook(({ list }) => useAllPages(list), { initialProps: { list: page(true, false) } });
    expect(fetchNext).toHaveBeenCalledTimes(1);
    rerender({ list: page(true, true) });     // the second page on its way: no second ask
    expect(fetchNext).toHaveBeenCalledTimes(1);
    rerender({ list: page(true, false) });    // it arrived, and there is a third
    expect(fetchNext).toHaveBeenCalledTimes(2);
    rerender({ list: page(false, false) });   // the last
    expect(fetchNext).toHaveBeenCalledTimes(2);
    expect(complete(page(false, false))).toBe(true);
    expect(complete(page(true, false))).toBe(false);
  });
});

describe("a workspace member's name", () => {
  const menu = (complete: boolean) => ({ orgMembers: [{ id: "u1", name: "Sara", email: "sara@x.co" }], orgMembersComplete: complete }) as unknown as WorkspacesMenu;

  it("is the org's name for them, never their id", () => {
    expect(nameIn(menu(true), "u1")).toBe("Sara");
    expect(nameIn(menu(false), "u9")).toBe("…");                // the list is still coming in
    expect(nameIn(menu(true), "u9")).toBe("Former member");     // the list is complete: they left the org
  });

  it("is found by name or by email", () => {
    const people = [{ id: "u1", name: "Sara Ali", email: "sara@x.co" }, { id: "u2", name: "Omar", email: "o@x.co" }];
    expect(findIn(people, "").map((p) => p.id)).toEqual(["u1", "u2"]);
    expect(findIn(people, "ali").map((p) => p.id)).toEqual(["u1"]);
    expect(findIn(people, "O@X").map((p) => p.id)).toEqual(["u2"]);
  });
});
