// The look a workspace's apps wear (docs/notes/apps.md, "Ready-made apps"): a few named ones and the company's own
// colour, each a set of shadcn/ui tokens for light and dark that an app built on them takes in place of its own. The
// server keeps the choice (`GET/PUT /apps/look`); the tokens are made here, where the picker shows them first.
// Values: shadcn/ui v4's base colours and accent themes, transcribed (tests/app-look.test.ts pins their shape).

export type Look = { look: string; color?: string };
export type Tokens = Record<string, string>;
export type LookTokens = { light: Tokens; dark: Tokens };
type Choice = { base: keyof typeof BASE; accent?: keyof typeof ACCENT; radius: number; primary?: string };

// Per base, in light then dark: background, foreground, card, primary, its text, secondary, muted text, border, ring.
type Nine = [string, string, string, string, string, string, string, string, string];
const BASE: Record<"neutral" | "zinc" | "slate" | "stone", [Nine, Nine]> = {
  neutral: [["oklch(1 0 0)", "oklch(0.145 0 0)", "oklch(1 0 0)", "oklch(0.205 0 0)", "oklch(0.985 0 0)", "oklch(0.97 0 0)", "oklch(0.556 0 0)", "oklch(0.922 0 0)", "oklch(0.708 0 0)"],
            ["oklch(0.145 0 0)", "oklch(0.985 0 0)", "oklch(0.205 0 0)", "oklch(0.922 0 0)", "oklch(0.205 0 0)", "oklch(0.269 0 0)", "oklch(0.708 0 0)", "oklch(1 0 0 / 10%)", "oklch(0.556 0 0)"]],
  zinc: [["oklch(1 0 0)", "oklch(0.141 0.005 285.823)", "oklch(1 0 0)", "oklch(0.21 0.006 285.885)", "oklch(0.985 0 0)", "oklch(0.967 0.001 286.375)", "oklch(0.552 0.016 285.938)", "oklch(0.92 0.004 286.32)", "oklch(0.705 0.015 286.067)"],
         ["oklch(0.141 0.005 285.823)", "oklch(0.985 0 0)", "oklch(0.21 0.006 285.885)", "oklch(0.92 0.004 286.32)", "oklch(0.21 0.006 285.885)", "oklch(0.274 0.006 286.033)", "oklch(0.705 0.015 286.067)", "oklch(1 0 0 / 10%)", "oklch(0.552 0.016 285.938)"]],
  slate: [["oklch(1 0 0)", "oklch(0.129 0.042 264.695)", "oklch(1 0 0)", "oklch(0.208 0.042 265.755)", "oklch(0.984 0.003 247.858)", "oklch(0.968 0.007 247.896)", "oklch(0.554 0.046 257.417)", "oklch(0.929 0.013 255.508)", "oklch(0.704 0.04 256.788)"],
          ["oklch(0.129 0.042 264.695)", "oklch(0.984 0.003 247.858)", "oklch(0.208 0.042 265.755)", "oklch(0.929 0.013 255.508)", "oklch(0.208 0.042 265.755)", "oklch(0.279 0.041 260.031)", "oklch(0.704 0.04 256.788)", "oklch(1 0 0 / 10%)", "oklch(0.551 0.027 264.364)"]],
  stone: [["oklch(1 0 0)", "oklch(0.147 0.004 49.25)", "oklch(1 0 0)", "oklch(0.216 0.006 56.043)", "oklch(0.985 0.001 106.423)", "oklch(0.97 0.001 106.424)", "oklch(0.553 0.013 58.071)", "oklch(0.923 0.003 48.717)", "oklch(0.709 0.01 56.259)"],
          ["oklch(0.147 0.004 49.25)", "oklch(0.985 0.001 106.423)", "oklch(0.216 0.006 56.043)", "oklch(0.923 0.003 48.717)", "oklch(0.216 0.006 56.043)", "oklch(0.268 0.007 34.298)", "oklch(0.709 0.01 56.259)", "oklch(1 0 0 / 10%)", "oklch(0.553 0.013 58.071)"]],
};
// An accent replaces the primary and its text: light, then dark.
const ACCENT = {
  blue: ["oklch(0.623 0.214 259.815)", "oklch(0.97 0.014 254.604)", "oklch(0.546 0.245 262.881)", "oklch(0.97 0.014 254.604)"],
  green: ["oklch(0.723 0.219 149.579)", "oklch(0.982 0.018 155.826)", "oklch(0.696 0.17 162.48)", "oklch(0.393 0.095 152.535)"],
  orange: ["oklch(0.705 0.213 47.604)", "oklch(0.98 0.016 73.684)", "oklch(0.646 0.222 41.116)", "oklch(0.98 0.016 73.684)"],
  rose: ["oklch(0.645 0.246 16.439)", "oklch(0.969 0.015 12.422)", "oklch(0.645 0.246 16.439)", "oklch(0.969 0.015 12.422)"],
};

export const LOOKS: Record<string, Choice> = {
  classic: { base: "neutral", radius: 0.625 },
  ocean: { base: "slate", accent: "blue", radius: 0.75 },
  palm: { base: "zinc", accent: "green", radius: 0.75 },
  sand: { base: "stone", accent: "orange", radius: 0.75 },
  rose: { base: "neutral", accent: "rose", radius: 1 },
};
export const isHex = (v: unknown): v is string => typeof v === "string" && /^#[0-9a-fA-F]{6}$/.test(v);

// The text on a company colour: whichever of white and near black reads better on it (WCAG contrast).
function onColor(hex: string) {
  const l = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
    .reduce((s, v, i) => s + v * [0.2126, 0.7152, 0.0722][i], 0);
  return 1.05 / (l + 0.05) >= (l + 0.05) / 0.05 ? "#ffffff" : "#0a0a0a";
}

function side(c: Choice, dark: boolean): Tokens {
  const [bg, fg, card, basePrimary, basePrimaryFg, secondary, mutedFg, border, ring] = BASE[c.base][dark ? 1 : 0];
  const a = c.accent && ACCENT[c.accent];
  const primary = c.primary ?? (a ? a[dark ? 2 : 0] : basePrimary);
  const primaryFg = c.primary ? onColor(c.primary) : a ? a[dark ? 3 : 1] : basePrimaryFg;
  const focus = a || c.primary ? primary : ring, onSecondary = dark ? fg : basePrimary;
  return {
    "--radius": `${c.radius}rem`, "--background": bg, "--foreground": fg, "--card": card, "--card-foreground": fg,
    "--popover": card, "--popover-foreground": fg, "--primary": primary, "--primary-foreground": primaryFg,
    "--secondary": secondary, "--secondary-foreground": onSecondary, "--muted": secondary, "--muted-foreground": mutedFg,
    "--accent": secondary, "--accent-foreground": onSecondary, "--border": border, "--input": dark ? "oklch(1 0 0 / 15%)" : border,
    "--ring": focus, "--sidebar": dark ? card : basePrimaryFg, "--sidebar-foreground": fg, "--sidebar-primary": primary,
    "--sidebar-primary-foreground": primaryFg, "--sidebar-accent": secondary, "--sidebar-accent-foreground": onSecondary,
    "--sidebar-border": border, "--sidebar-ring": focus,
  };
}

export function lookTokens(look: Look): LookTokens | null {
  const c = look.look === "custom" && isHex(look.color) ? { base: "neutral" as const, radius: 0.75, primary: look.color.toLowerCase() } : LOOKS[look.look];
  return c ? { light: side(c, false), dark: side(c, true) } : null;
}

// The workspace's look as this page knows it, read by every open app's bridge. None: each app keeps its own.
let current: LookTokens | null = null;
const listeners = new Set<() => void>();
export const currentLook = () => current;
export function setLook(look: Look | null) {
  current = look ? lookTokens(look) : null;
  listeners.forEach((fn) => fn());
}
export function onLook(fn: () => void) {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}
