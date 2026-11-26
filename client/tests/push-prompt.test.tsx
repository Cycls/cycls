import { render, screen, cleanup, fireEvent, act } from "@testing-library/react";
import { test, expect, afterEach, vi } from "vitest";
import { Surfaces } from "../src/components/surfaces";
import { askPush, _resetPush } from "../src/lib/notifications";

// Asking for push is on by default: after the first finished task, and at the moments that earn it, in their words.

vi.mock("../src/lib/analytics", () => ({ track: vi.fn(), setPerson: vi.fn(), flagsProvider: () => null }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); localStorage.clear(); _resetPush(); });

test("the card asks after the first finished task, and a routine just set up asks again in its own words", () => {
  vi.stubGlobal("Notification", { permission: "default", requestPermission: vi.fn() });
  const config = { notifications: [{ provider: "onesignal", app_id: "1de3d91b-15da-4964-9ab7-741e3cfbde0c" }] } as never;
  const { rerender } = render(<Surfaces config={config} ready={false} active />);
  expect(screen.queryByText("Turn on notifications")).toBeNull();
  rerender(<Surfaces config={config} ready active />);
  fireEvent.click(screen.getByText("Not now"));
  expect(screen.queryByText("Turn on notifications")).toBeNull();
  act(() => askPush("routine"));
  expect(screen.getByText("Get this routine's news")).toBeTruthy();
});
