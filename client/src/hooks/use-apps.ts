import { useState, useCallback, useEffect, useRef } from "react";
import { useApi } from "./use-api";

// Mini apps live in `apps/<slug>/` at the workspace root, entry `index.html`.
// A folder rather than a loose file so an app's data sits beside it — which is
// also exactly the boundary the canvas bridge will read within.

export const APPS_DIR = "apps";

export interface MiniAppInfo {
  slug: string;
  name: string;
  /** Emoji or short text, when the icon isn't an image. */
  icon?: string;
  /** Ready-to-render image source (a data: URI, or a blob: URL once fetched). */
  iconSrc?: string;
  /** Workspace path of an image icon, pending an authed fetch. */
  iconFile?: string;
  /** Always present: what to draw when there is no emoji and no image. */
  letter: string;
  description?: string;
  entry: string;
}

interface Manifest {
  name?: unknown;
  icon?: unknown;
  description?: unknown;
}

const IMAGE_EXT = /\.(png|jpe?g|svg|webp|gif|avif)$/i;

const str = (v: unknown, max: number) =>
  typeof v === "string" && v.trim() ? v.trim().slice(0, max) : undefined;

// Titleise the folder name so an app without a manifest still reads properly.
const titleise = (slug: string) =>
  slug.replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

// First character of the name, uppercased — works for Arabic and emoji names
// too, since we split by code point rather than by UTF-16 unit.
const firstLetter = (name: string) => [...name][0]?.toUpperCase() ?? "?";

export function parseManifest(slug: string, raw: string | null): MiniAppInfo {
  let m: Manifest = {};
  if (raw) {
    try {
      const parsed: unknown = JSON.parse(raw);
      if (parsed && typeof parsed === "object") m = parsed as Manifest;
    } catch {
      // A broken manifest degrades to the folder name; it never hides the app.
    }
  }
  const name = str(m.name, 60) ?? titleise(slug);
  const icon = str(m.icon, 512);
  const app: MiniAppInfo = {
    slug,
    name,
    letter: firstLetter(name),
    description: str(m.description, 200),
    entry: `${APPS_DIR}/${slug}/index.html`,
  };
  if (!icon) return app;
  if (icon.startsWith("data:image/")) app.iconSrc = icon;
  else if (IMAGE_EXT.test(icon) && !/^[a-z]+:/i.test(icon)) {
    // Relative to the app's folder; /files is bearer-only, so it needs fetching.
    app.iconFile = `${APPS_DIR}/${slug}/${icon.replace(/^\/+/, "")}`;
  } else if (!icon.includes("/") && icon.length <= 8) app.icon = icon;
  return app;
}

export function useApps(baseUrl: string = "") {
  const [apps, setApps] = useState<MiniAppInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const { api } = useApi(baseUrl);
  const blobs = useRef<string[]>([]);

  const refresh = useCallback(async () => {
    const stale = blobs.current;
    blobs.current = [];
    try {
      const res = await api(`/files?path=${APPS_DIR}`);
      if (!res.ok) {
        setApps([]);
        return;
      }
      const entries = (await res.json()) as { name: string; type: string }[];
      const slugs = entries
        .filter((e) => e.type === "directory" && !e.name.startsWith("."))
        .map((e) => e.name)
        .sort();
      setApps(
        await Promise.all(
          slugs.map(async (slug) => {
            const r = await api(`/files/${APPS_DIR}/${slug}/app.json`).catch(() => null);
            const app = parseManifest(slug, r && r.ok ? await r.text() : null);
            if (!app.iconFile) return app;
            try {
              const img = await api(`/files/${app.iconFile}`);
              if (!img.ok) return app;
              const url = URL.createObjectURL(await img.blob());
              blobs.current.push(url);
              return { ...app, iconSrc: url };
            } catch {
              return app;   // a missing icon falls back to the letter
            }
          }),
        ),
      );
    } catch {
      setApps([]);
    } finally {
      setLoading(false);
      stale.forEach(URL.revokeObjectURL);
    }
  }, [api]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => () => blobs.current.forEach(URL.revokeObjectURL), []);

  return { apps, loading, refresh };
}
