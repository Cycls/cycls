// The workspace's app theme: the shadcn/ui tokens every app gets in `cycls:init`, and again in a
// `{type: "theme"}` command when an admin changes it or the host flips light/dark
// (docs/notes/apps.md, "The theme"). The server keeps only the choice (`GET/PUT /apps/theme`);
// the tokens are derived here, which the Theme panel's live preview needs before anything is saved.
//
// No imports on purpose: the phone client mirrors this file into its shared `src/core/apps.mjs`,
// as it does `appScope`/`canWrite`, so both hosts hand an app the same colors.
//
// Values: shadcn/ui v4 (Tailwind v4, OKLCH) — the four base colors of `components.json`
// (neutral, zinc, slate, stone) and the accent themes of ui.shadcn.com/themes. Transcribed, so
// `tests/app-theme.test.ts` pins the shape, not each number: re-check against shadcn on upgrade.

export const BASES = ["neutral", "zinc", "slate", "stone"] as const;
export const COLORS = ["base", "blue", "green", "orange", "red", "rose", "violet", "yellow"] as const;
export const RADII = [0, 0.3, 0.5, 0.625, 0.75, 1] as const;
export type Base = (typeof BASES)[number];
export type Color = (typeof COLORS)[number];
export type AppThemeChoice = { base: Base; color: Color; radius: number; primary?: string };
export type Tokens = Record<string, string>;
export type AppTokens = { light: Tokens; dark: Tokens };

export const DEFAULT_CHOICE: AppThemeChoice = { base: "neutral", color: "base", radius: 0.625 };

// Per base: [background, foreground, card, primary, primaryFg, secondary, mutedFg, border, ring] in light,
// then the same nine in dark. Everything else in shadcn's list is one of these.
type Nine = [string, string, string, string, string, string, string, string, string];
const BASE: Record<Base, { light: Nine; dark: Nine }> = {
  neutral: {
    light: ["oklch(1 0 0)", "oklch(0.145 0 0)", "oklch(1 0 0)", "oklch(0.205 0 0)", "oklch(0.985 0 0)",
            "oklch(0.97 0 0)", "oklch(0.556 0 0)", "oklch(0.922 0 0)", "oklch(0.708 0 0)"],
    dark: ["oklch(0.145 0 0)", "oklch(0.985 0 0)", "oklch(0.205 0 0)", "oklch(0.922 0 0)", "oklch(0.205 0 0)",
           "oklch(0.269 0 0)", "oklch(0.708 0 0)", "oklch(1 0 0 / 10%)", "oklch(0.556 0 0)"],
  },
  zinc: {
    light: ["oklch(1 0 0)", "oklch(0.141 0.005 285.823)", "oklch(1 0 0)", "oklch(0.21 0.006 285.885)", "oklch(0.985 0 0)",
            "oklch(0.967 0.001 286.375)", "oklch(0.552 0.016 285.938)", "oklch(0.92 0.004 286.32)", "oklch(0.705 0.015 286.067)"],
    dark: ["oklch(0.141 0.005 285.823)", "oklch(0.985 0 0)", "oklch(0.21 0.006 285.885)", "oklch(0.92 0.004 286.32)",
           "oklch(0.21 0.006 285.885)", "oklch(0.274 0.006 286.033)", "oklch(0.705 0.015 286.067)", "oklch(1 0 0 / 10%)",
           "oklch(0.552 0.016 285.938)"],
  },
  slate: {
    light: ["oklch(1 0 0)", "oklch(0.129 0.042 264.695)", "oklch(1 0 0)", "oklch(0.208 0.042 265.755)", "oklch(0.984 0.003 247.858)",
            "oklch(0.968 0.007 247.896)", "oklch(0.554 0.046 257.417)", "oklch(0.929 0.013 255.508)", "oklch(0.704 0.04 256.788)"],
    dark: ["oklch(0.129 0.042 264.695)", "oklch(0.984 0.003 247.858)", "oklch(0.208 0.042 265.755)", "oklch(0.929 0.013 255.508)",
           "oklch(0.208 0.042 265.755)", "oklch(0.279 0.041 260.031)", "oklch(0.704 0.04 256.788)", "oklch(1 0 0 / 10%)",
           "oklch(0.551 0.027 264.364)"],
  },
  stone: {
    light: ["oklch(1 0 0)", "oklch(0.147 0.004 49.25)", "oklch(1 0 0)", "oklch(0.216 0.006 56.043)", "oklch(0.985 0.001 106.423)",
            "oklch(0.97 0.001 106.424)", "oklch(0.553 0.013 58.071)", "oklch(0.923 0.003 48.717)", "oklch(0.709 0.01 56.259)"],
    dark: ["oklch(0.147 0.004 49.25)", "oklch(0.985 0.001 106.423)", "oklch(0.216 0.006 56.043)", "oklch(0.923 0.003 48.717)",
           "oklch(0.216 0.006 56.043)", "oklch(0.268 0.007 34.298)", "oklch(0.709 0.01 56.259)", "oklch(1 0 0 / 10%)",
           "oklch(0.553 0.013 58.071)"],
  },
};

// An accent theme replaces the primary family only: [primary, primaryFg] light, then dark.
const ACCENT: Record<Exclude<Color, "base">, [string, string, string, string]> = {
  blue:   ["oklch(0.623 0.214 259.815)", "oklch(0.97 0.014 254.604)", "oklch(0.546 0.245 262.881)", "oklch(0.97 0.014 254.604)"],
  green:  ["oklch(0.723 0.219 149.579)", "oklch(0.982 0.018 155.826)", "oklch(0.696 0.17 162.48)", "oklch(0.393 0.095 152.535)"],
  orange: ["oklch(0.705 0.213 47.604)", "oklch(0.98 0.016 73.684)", "oklch(0.646 0.222 41.116)", "oklch(0.98 0.016 73.684)"],
  red:    ["oklch(0.637 0.237 25.331)", "oklch(0.971 0.013 17.38)", "oklch(0.637 0.237 25.331)", "oklch(0.971 0.013 17.38)"],
  rose:   ["oklch(0.645 0.246 16.439)", "oklch(0.969 0.015 12.422)", "oklch(0.645 0.246 16.439)", "oklch(0.969 0.015 12.422)"],
  violet: ["oklch(0.606 0.25 292.717)", "oklch(0.969 0.016 293.756)", "oklch(0.541 0.281 293.009)", "oklch(0.969 0.016 293.756)"],
  yellow: ["oklch(0.795 0.184 86.047)", "oklch(0.421 0.095 57.708)", "oklch(0.795 0.184 86.047)", "oklch(0.421 0.095 57.708)"],
};

// The swatch a picker shows for each choice: the light primary.
export const SWATCH: Record<Base | Exclude<Color, "base">, string> = {
  neutral: "oklch(0.556 0 0)", zinc: "oklch(0.552 0.016 285.938)", slate: "oklch(0.554 0.046 257.417)",
  stone: "oklch(0.553 0.013 58.071)",
  ...Object.fromEntries(Object.entries(ACCENT).map(([k, v]) => [k, v[0]])) as Record<Exclude<Color, "base">, string>,
};

const CHARTS = {
  light: ["oklch(0.646 0.222 41.116)", "oklch(0.6 0.118 184.704)", "oklch(0.398 0.07 227.392)", "oklch(0.828 0.189 84.429)", "oklch(0.769 0.188 70.08)"],
  dark: ["oklch(0.488 0.243 264.376)", "oklch(0.696 0.17 162.48)", "oklch(0.769 0.188 70.08)", "oklch(0.627 0.265 303.9)", "oklch(0.645 0.246 16.439)"],
};
const DESTRUCTIVE = { light: "oklch(0.577 0.245 27.325)", dark: "oklch(0.704 0.191 22.216)" };

// WCAG relative luminance of #rrggbb, for the text that sits on a brand color.
function luminance(hex: string): number {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}
export function onColor(hex: string): string {
  const l = luminance(hex);
  return (1.05 / (l + 0.05)) >= ((l + 0.05) / 0.05) ? "#ffffff" : "#0a0a0a";
}
export const isHex = (v: unknown): v is string => typeof v === "string" && /^#[0-9a-fA-F]{6}$/.test(v);

function side(choice: AppThemeChoice, mode: "light" | "dark"): Tokens {
  const [bg, fg, card, basePrimary, basePrimaryFg, secondary, mutedFg, border, ring] = BASE[choice.base][mode];
  let primary = basePrimary, primaryFg = basePrimaryFg, focus = ring;
  if (choice.color !== "base") {
    const a = ACCENT[choice.color];
    [primary, primaryFg] = mode === "light" ? [a[0], a[1]] : [a[2], a[3]];
    focus = primary;
  }
  if (isHex(choice.primary)) {
    primary = choice.primary.toLowerCase();
    primaryFg = onColor(primary);
    focus = primary;
  }
  const t: Tokens = {
    "--radius": `${choice.radius}rem`,
    "--background": bg, "--foreground": fg,
    "--card": card, "--card-foreground": fg,
    "--popover": card, "--popover-foreground": fg,
    "--primary": primary, "--primary-foreground": primaryFg,
    "--secondary": secondary, "--secondary-foreground": mode === "light" ? basePrimary : fg,
    "--muted": secondary, "--muted-foreground": mutedFg,
    "--accent": secondary, "--accent-foreground": mode === "light" ? basePrimary : fg,
    "--destructive": DESTRUCTIVE[mode],
    "--border": border, "--input": mode === "light" ? border : "oklch(1 0 0 / 15%)", "--ring": focus,
    "--sidebar": mode === "light" ? BASE[choice.base].light[4] : card,
    "--sidebar-foreground": fg,
    "--sidebar-primary": primary, "--sidebar-primary-foreground": primaryFg,
    "--sidebar-accent": secondary, "--sidebar-accent-foreground": mode === "light" ? basePrimary : fg,
    "--sidebar-border": border, "--sidebar-ring": focus,
  };
  CHARTS[mode].forEach((c, i) => { t[`--chart-${i + 1}`] = i === 0 && choice.color !== "base" ? primary : c; });
  return t;
}

export function themeTokens(choice: AppThemeChoice): AppTokens {
  return { light: side(choice, "light"), dark: side(choice, "dark") };
}

// A choice from the server, made safe: whatever is unknown falls back to the default.
export function normalize(raw: unknown): AppThemeChoice | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const out: AppThemeChoice = {
    base: (BASES as readonly string[]).includes(r.base as string) ? (r.base as Base) : DEFAULT_CHOICE.base,
    color: (COLORS as readonly string[]).includes(r.color as string) ? (r.color as Color) : DEFAULT_CHOICE.color,
    radius: (RADII as readonly number[]).includes(r.radius as number) ? (r.radius as number) : DEFAULT_CHOICE.radius,
  };
  if (isHex(r.primary)) out.primary = r.primary.toLowerCase();
  return out;
}

// ---- The host's current choice, read by every open app's bridge ----------------------------
//
// One per page: the workspace's own, else the agent's default, else none — and none means apps
// keep their own look, which is every app today. Nothing is sent to an app until a choice exists.

let current: AppThemeChoice | null = null;
const listeners = new Set<() => void>();

export function getAppTheme(): AppThemeChoice | null { return current; }
export function setAppTheme(choice: AppThemeChoice | null) {
  current = choice;
  listeners.forEach((fn) => { try { fn(); } catch { /* one bad listener never blocks the rest */ } });
}
export function subscribeAppTheme(fn: () => void): () => void {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}
// What an app's `cycls:init` (and a theme command) carries beside `theme: "light" | "dark"`.
export function appThemeContext(): { tokens?: AppTokens } {
  return current ? { tokens: themeTokens(current) } : {};
}
