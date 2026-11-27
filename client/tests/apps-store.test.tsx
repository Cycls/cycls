import { describe, it, expect, afterEach, vi } from "vitest";
import { render, cleanup, fireEvent, screen } from "@testing-library/react";
import { AppsGallery, AppsStore, type Catalog, type Offered } from "../src/components/apps-store";
import { LOOKS, lookTokens } from "../src/lib/app-look";

// Ready-made apps: the store an empty Apps panel shows, and the gallery's cards, search and looks.

afterEach(cleanup);
const two = (en: string) => ({ en, ar: "" });
const app = (slug: string, state: Offered["state"], extra: Partial<Offered> = {}): Offered =>
  ({ slug, title: two(slug), description: two(`${slug} line`), category: two("Work"), state, ...extra });
const actions = () => ({ agent: "Super", busy: null, onPeek: vi.fn(), onInstall: vi.fn(), onBuild: vi.fn() });

describe("the store in an empty Apps panel", () => {
  it("features one, lists picks, and installs only for an admin", () => {
    const a = actions();
    const catalog: Catalog = { admin: true, apps: [app("crm", "available"), app("tasks", "available", { featured: true })] };
    const { rerender } = render(<AppsStore catalog={catalog} actions={a} onGallery={() => {}} />);
    expect(screen.getByText("Featured")).toBeTruthy();
    fireEvent.click(screen.getAllByRole("button", { name: "Install" })[0]);
    expect(a.onInstall.mock.calls[0][0].slug).toBe("tasks");
    fireEvent.click(screen.getByRole("button", { name: /Ask Super to build your app/ }));
    expect(a.onBuild).toHaveBeenCalled();
    rerender(<AppsStore catalog={{ ...catalog, admin: false }} actions={a} onGallery={() => {}} />);
    expect(screen.queryByRole("button", { name: "Install" })).toBeNull();
  });
});

describe("the gallery", () => {
  const props = (apps: Offered[]) => ({ catalog: { admin: true, apps }, actions: actions(), onOpen: vi.fn(), onRemove: vi.fn(), look: null, onLook: vi.fn(async () => {}) });

  it("shows each app's state and what can be done with it", () => {
    const p = props([app("tasks", "installed"), app("kpi", "update"), app("docs", "changed"), app("crm", "available")]);
    render(<AppsGallery {...p} />);
    expect(screen.getAllByRole("button", { name: "Open" })).toHaveLength(3);
    expect(screen.getByText("Update available")).toBeTruthy();
    expect(screen.getByText("Changed here")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Update" })).toHaveLength(1);   // a changed app gets none
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(p.actions.onPeek.mock.calls[0][0].slug).toBe("crm");
    fireEvent.click(screen.getAllByRole("button", { name: "Remove" })[0]);
    expect(p.onRemove.mock.calls[0][0].slug).toBe("tasks");
  });

  it("offers to build what a search does not find", () => {
    const p = props([app("tasks", "available")]);
    render(<AppsGallery {...p} />);
    fireEvent.change(screen.getByPlaceholderText("Search apps"), { target: { value: "payroll" } });
    expect(screen.getByText("No app does that yet")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Ask Super to build it/ }));
    expect(p.actions.onBuild).toHaveBeenCalledWith("payroll");
  });

  it("picks a look by its picture and saves it", () => {
    const p = props([app("tasks", "available")]);
    render(<AppsGallery {...p} />);
    fireEvent.click(screen.getByRole("tab", { name: "Look" }));
    fireEvent.click(screen.getByRole("button", { name: /Ocean/ }));
    fireEvent.click(screen.getByRole("button", { name: "Use this look" }));
    expect(p.onLook).toHaveBeenCalledWith({ look: "ocean" });
  });
});

describe("looks", () => {
  it("each gives the same tokens in light and dark, and a company colour its own readable text", () => {
    for (const look of [...Object.keys(LOOKS).map((l) => ({ look: l })), { look: "custom", color: "#f5c400" }]) {
      const t = lookTokens(look)!;
      expect(Object.keys(t.light).sort()).toEqual(Object.keys(t.dark).sort());
      expect(t.light["--primary"]).toBeTruthy();
    }
    expect(lookTokens({ look: "custom", color: "#f5c400" })!.light["--primary-foreground"]).toBe("#0a0a0a");
    expect(lookTokens({ look: "custom", color: "#0b6b5d" })!.light["--primary-foreground"]).toBe("#ffffff");
    expect(lookTokens({ look: "neon" })).toBeNull();
  });
});
