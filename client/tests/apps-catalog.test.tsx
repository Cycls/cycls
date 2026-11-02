import { describe, it, expect, vi, afterEach } from "vitest";
import { useRef, useState } from "react";
import { render, screen, fireEvent, cleanup, waitFor, within } from "@testing-library/react";
import { AppsCatalog, type CatalogApp } from "../src/components/apps-catalog";
import { InputBox, type MenuApp } from "../src/components/input-box";
import { getAppTheme, setAppTheme } from "../src/lib/app-theme";
import { setLang } from "../src/lib/i18n";

vi.mock("../src/lib/analytics", () => ({ track: vi.fn() }));

const APPS: CatalogApp[] = [
  { slug: "tasks", name: "Tasks", name_ar: "المهام", icon: "✅", category: "Work", category_ar: "العمل",
    description: "Kanban of follow-ups", version: "aaa", bytes: 808_000, state: "installed" },
  { slug: "crm", name: "CRM", icon: "🤝", category: "Sales", description: "Deals", version: "bbb", bytes: 640_000, state: "available" },
  { slug: "kpi", name: "KPI", icon: "📈", category: "Work", version: "ccc", bytes: 512_000, state: "update" },
  { slug: "forms", name: "Forms", icon: "📝", category: "Sales", version: "ddd", bytes: 300_000, state: "conflict" },
];

function fakeApi({ admin = true, theme = null as unknown } = {}) {
  const calls: { path: string; method: string; json?: unknown }[] = [];
  const api = vi.fn(async (path: string, init?: { method?: string; json?: unknown }) => {
    calls.push({ path, method: init?.method ?? "GET", json: init?.json });
    const body = path === "/apps/catalog" ? { apps: APPS, admin }
      : path === "/apps/theme" && !init?.method ? { theme, default: null, admin }
      : { ok: true };
    return new Response(JSON.stringify(body), { status: 200 });
  });
  return { api: api as unknown as Parameters<typeof AppsCatalog>[0]["api"], calls };
}

describe("the Apps section", () => {
  afterEach(() => { cleanup(); setLang("en"); setAppTheme(null); });

  it("puts installed apps first and each card's actions in its state", async () => {
    const { api } = fakeApi();
    const { container } = render(<AppsCatalog api={api} onOpen={() => {}} />);
    await screen.findByText("Tasks");
    const order = [...container.querySelectorAll("[data-app]")].map((n) => n.getAttribute("data-app"));
    expect(order).toEqual(["tasks", "kpi", "crm", "forms"]);
    const card = (slug: string) => within(container.querySelector(`[data-app="${slug}"]`) as HTMLElement);
    expect(card("tasks").getByText("Open")).toBeTruthy();
    expect(card("tasks").getByText("Remove")).toBeTruthy();
    expect(card("kpi").getAllByText("Update available").length).toBeGreaterThan(0);
    expect(card("kpi").getByText("Update")).toBeTruthy();
    expect(card("crm").getByText("Install")).toBeTruthy();
    expect(card("forms").queryByText("Install")).toBeNull();          // a person's own app is never overwritten
    expect(card("forms").getByText("One of your apps has this name")).toBeTruthy();
    expect(card("tasks").getByText(/Work · 789 KB/)).toBeTruthy();
  });

  it("installs, then opens the app in the canvas", async () => {
    const { api, calls } = fakeApi();
    const onOpen = vi.fn(), onChanged = vi.fn();
    render(<AppsCatalog api={api} onOpen={onOpen} onChanged={onChanged} />);
    fireEvent.click(await screen.findByText("Install"));
    await waitFor(() => expect(onOpen).toHaveBeenCalledWith("apps/crm/index.html", "CRM"));
    expect(calls).toContainEqual({ path: "/apps/install", method: "POST", json: { slug: "crm" } });
    expect(onChanged).toHaveBeenCalled();
  });

  it("narrows by category chip and by search", async () => {
    const { api } = fakeApi();
    const { container } = render(<AppsCatalog api={api} onOpen={() => {}} />);
    await screen.findByText("Tasks");
    fireEvent.click(screen.getByRole("button", { name: "Sales" }));
    expect([...container.querySelectorAll("[data-app]")].map((n) => n.getAttribute("data-app"))).toEqual(["crm", "forms"]);
    fireEvent.click(screen.getByRole("button", { name: "All" }));
    fireEvent.change(screen.getByPlaceholderText("Search apps"), { target: { value: "follow" } });
    expect([...container.querySelectorAll("[data-app]")].map((n) => n.getAttribute("data-app"))).toEqual(["tasks"]);
  });

  it("shows a member what is there, and no button that would change it", async () => {
    const { api } = fakeApi({ admin: false });
    render(<AppsCatalog api={api} onOpen={() => {}} />);
    await screen.findByText("Tasks");
    expect(screen.getByText(/Only workspace admins can install/)).toBeTruthy();
    expect(screen.queryByText("Install")).toBeNull();
    expect(screen.queryByText("Remove")).toBeNull();
    expect(screen.getAllByText("Open").length).toBe(2);
  });

  it("reads Arabic names and categories in Arabic", async () => {
    setLang("ar");
    const { api } = fakeApi();
    render(<AppsCatalog api={api} onOpen={() => {}} />);
    expect(await screen.findByText("المهام")).toBeTruthy();
    expect(screen.getByRole("button", { name: "العمل" })).toBeTruthy();
  });

  it("saves a theme for the workspace and hands it to every open app", async () => {
    const { api, calls } = fakeApi();
    render(<AppsCatalog api={api} onOpen={() => {}} initialView="theme" />);
    fireEvent.click(await screen.findByRole("button", { name: /Zinc/ }));
    fireEvent.click(screen.getByRole("button", { name: /Violet/ }));
    fireEvent.click(screen.getByRole("button", { name: "0.5" }));
    expect(document.querySelectorAll("[data-preview]")).toHaveLength(2);   // light and dark, live
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(getAppTheme()).toEqual({ base: "zinc", color: "violet", radius: 0.5 }));
    expect(calls).toContainEqual({ path: "/apps/theme", method: "PUT", json: { theme: { base: "zinc", color: "violet", radius: 0.5 } } });
  });

  it("locks the theme for a member", async () => {
    const { api } = fakeApi({ admin: false });
    render(<AppsCatalog api={api} onOpen={() => {}} initialView="theme" />);
    expect(await screen.findByText(/Only workspace admins can change the theme/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /Zinc/ }).matches(":disabled")).toBe(true);   // the fieldset disables every control
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });
});

describe("the + menu's Apps", () => {
  afterEach(cleanup);
  const apps: MenuApp[] = [{ slug: "tasks", name: "Tasks", icon: "✅", entry: "apps/tasks/index.html" }];

  function Harness(props: { onOpenApp: (a: MenuApp) => void; onBrowseApps: () => void }) {
    const ref = useRef<HTMLTextAreaElement>(null);
    const [input, setInput] = useState("");
    return (
      <InputBox textareaRef={ref} input={input} setInput={setInput} handleKeyDown={() => {}} handleSubmit={() => {}}
        isStreaming={false} onStop={() => {}} listening={false} transcribing={false}
        startMic={() => {}} stopMic={() => {}} cancelMic={() => {}}
        onOpenFilePicker={() => {}} onOpenSkills={() => {}} apps={apps} {...props} />
    );
  }

  it("sits under Skills and drills into installed apps and Browse apps…", () => {
    const onOpenApp = vi.fn(), onBrowseApps = vi.fn();
    render(<Harness onOpenApp={onOpenApp} onBrowseApps={onBrowseApps} />);
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    const labels = screen.getAllByRole("button").map((b) => b.textContent);
    expect(labels.indexOf("Apps")).toBe(labels.indexOf("Skills") + 1);
    fireEvent.click(screen.getByRole("button", { name: "Apps" }));
    fireEvent.click(screen.getByRole("menuitem", { name: /Tasks/ }));
    expect(onOpenApp).toHaveBeenCalledWith(apps[0]);
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    fireEvent.click(screen.getByRole("button", { name: "Apps" }));
    fireEvent.click(screen.getByRole("menuitem", { name: /Browse apps/ }));
    expect(onBrowseApps).toHaveBeenCalled();
  });
});
