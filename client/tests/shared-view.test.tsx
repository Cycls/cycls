import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, cleanup, screen, fireEvent } from "@testing-library/react";
import { SharedView } from "../src/components/shared-view";
import { getThemeMode } from "../src/lib/utils";

// A shared page's way in: "Sign in" for a visitor (the sign-in page), "Go to <agent>" once signed in, and no
// theme toggle, since a shared page follows the system.

beforeEach(() => {
  window.history.pushState({}, "", "/shared/u/tok1");
  vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));   // the share stays loading: the bar is what's tested
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.history.pushState({}, "", "/"); });

describe("the shared page's bar", () => {
  it("offers a visitor the sign-in page", () => {
    const onSignIn = vi.fn();
    render(<SharedView agent="Super" onSignIn={onSignIn} />);
    fireEvent.click(screen.getByText("Sign in"));
    expect(onSignIn).toHaveBeenCalledOnce();
    expect(screen.queryByLabelText("Toggle theme")).toBeNull();
  });

  it("leads a signed-in reader to the agent", () => {
    render(<SharedView agent="Super" signedIn onSignIn={() => {}} />);
    expect(screen.getByText("Go to Super").closest("a")?.getAttribute("href")).toBe("/");
    expect(screen.queryByText("Sign in")).toBeNull();
  });

  it("follows the system theme, whatever the app saved", () => {
    localStorage.setItem("cycls_theme", "dark");
    expect(getThemeMode()).toBe("system");
    window.history.pushState({}, "", "/");
    expect(getThemeMode()).toBe("dark");
    localStorage.removeItem("cycls_theme");
  });
});
