// Screenshots for ../screenshots, against the harness (npx vite --config vite.config.mjs --port 5199).
//   node shoot.mjs [playwright module path]
// Playwright is not a client dependency; pass the folder of one that is installed.
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

const base = process.argv[2] || "C:/Users/domin/Downloads/cycls-default-apps/";
const { chromium } = createRequire(base.endsWith("/") ? base : base + "/")("playwright");
const OUT = fileURLToPath(new URL("../screenshots/", import.meta.url));
mkdirSync(OUT, { recursive: true });
const URL_ = "http://localhost:5199/";

const browser = await chromium.launch();
const desk = { viewport: { width: 1280, height: 820 }, deviceScaleFactor: 2 };
const phone = { viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true };

async function shot(name, query, ctx, act) {
  const context = await browser.newContext(ctx);
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(URL_ + "?" + query);
  await page.waitForTimeout(700);
  if (act) await act(page);
  await page.screenshot({ path: OUT + name + ".png" });
  if (errors.length) console.log(name, "page errors:", errors);
  console.log("✓", name);
  await context.close();
}

const openApps = async (p, add = "Add", apps = "Apps") => {
  await p.getByRole("button", { name: add, exact: true }).click();
  await p.waitForTimeout(150);
  await p.getByRole("button", { name: apps, exact: true }).click();
  await p.waitForTimeout(200);
};

await shot("01-plus-menu", "scene=menu", desk, async (p) => { await p.getByRole("button", { name: "Add", exact: true }).click(); await p.waitForTimeout(200); });
await shot("02-plus-menu-apps-submenu", "scene=menu", desk, (p) => openApps(p));
await shot("03-apps-catalog", "scene=catalog", desk);
await shot("04-apps-catalog-member", "scene=catalog&admin=0", desk);
await shot("05-apps-catalog-dark", "scene=catalog&dark=1", desk);
await shot("06-theme-panel", "scene=theme", desk, async (p) => {
  await p.getByRole("button", { name: /Zinc/ }).click();
  await p.getByRole("button", { name: /Violet/ }).click();
  await p.getByRole("button", { name: "0.5", exact: true }).click();
  await p.waitForTimeout(150);
});
await shot("07-theme-panel-brand-color", "scene=theme", desk, async (p) => {
  await p.getByRole("button", { name: /Stone/ }).click();
  await p.getByPlaceholder("#0b6b5d").fill("#0b6b5d");
  await p.getByRole("button", { name: "1", exact: true }).click();
  await p.waitForTimeout(150);
});

// One app, three looks — the second and third pushed live (cycls:command theme), no reload.
const app = async (name, first, then) => shot(name, "scene=app" + (first ? `&palette=${first}` : ""), desk, async (p) => {
  await p.waitForTimeout(2600);
  if (then !== undefined) { await p.evaluate((t) => window.__theme(t), then); await p.waitForTimeout(500); }
});
await app("08-app-own-look", null);
await app("09-app-zinc-violet", "zinc-violet");
await app("10-app-stone-green-live", "zinc-violet", "stone-green");
await shot("11-app-dark-rose-live", "scene=app&palette=slate-rose&dark=1", desk, async (p) => { await p.waitForTimeout(2600); });

await shot("12-apps-catalog-ar", "scene=catalog&lang=ar", desk);
await shot("13-theme-panel-ar", "scene=theme&lang=ar", desk);
await shot("14-plus-menu-apps-ar", "scene=menu&lang=ar", desk, (p) => openApps(p, "Add", "التطبيقات"));
await shot("15-apps-catalog-phone", "scene=catalog", phone);
await shot("16-theme-panel-phone", "scene=theme&lang=ar", phone);
await shot("17-plus-menu-apps-phone", "scene=menu", phone, (p) => openApps(p));

await browser.close();
