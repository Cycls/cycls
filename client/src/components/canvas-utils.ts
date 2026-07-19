// Pure helpers for the canvas — kept out of canvas.tsx so that file exports
// only components (otherwise React Fast Refresh is disabled for it).

const ext = (name: string) => name.split(".").pop()?.toLowerCase() || "";

export const isHtml = (name: string) => ["html", "htm"].includes(ext(name));
export const isMd = (name: string) => ["md", "markdown"].includes(ext(name));
export const isPdf = (name: string) => ext(name) === "pdf";

const IMAGE_EXTS = new Set(["png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "ico", "avif"]);
export const isImage = (name: string) => IMAGE_EXTS.has(ext(name));

const AUDIO_EXTS = new Set(["mp3", "wav", "ogg", "oga", "m4a", "aac", "flac", "opus", "weba"]);
export const isAudio = (name: string) => AUDIO_EXTS.has(ext(name));

const VIDEO_EXTS = new Set(["mp4", "webm", "mov", "m4v", "ogv"]);
export const isVideo = (name: string) => VIDEO_EXTS.has(ext(name));

const SPREADSHEET_EXTS = new Set(["csv", "tsv", "xlsx", "xls", "ods"]);
export const isSpreadsheet = (name: string) => SPREADSHEET_EXTS.has(ext(name));

export const is3d = (name: string) => ["glb", "gltf"].includes(ext(name));

// Per-filetype accent — faint tile wash + label color for extension tiles.
const TINTS: Record<string, string> = {
  pdf: "#ff3b30", doc: "#2b7fff", docx: "#2b7fff", txt: "#8e8e93", md: "#8e8e93", rtf: "#8e8e93",
  xls: "#34c759", xlsx: "#34c759", csv: "#34c759", numbers: "#34c759",
  ppt: "#e8590c", pptx: "#e8590c", key: "#e8590c",
  mp4: "#ff2d55", mov: "#ff2d55", mp3: "#ff9500", wav: "#ff9500", m4a: "#ff9500",
  zip: "#8e8e93", tar: "#8e8e93", gz: "#8e8e93",
  json: "#ff9500", js: "#ff9500", ts: "#2b7fff", tsx: "#2b7fff", py: "#34c759", html: "#ff9500", css: "#2b7fff", sh: "#34c759",
  glb: "#af52de", gltf: "#af52de",
};
export const extTint = (name: string): string | undefined => TINTS[ext(name)];
// Wash + label styles for an extension tile; undefined → neutral (bg-secondary).
export const tintTile = (name: string) => {
  const c = extTint(name);
  return c ? { backgroundColor: c + "1f" } : undefined;
};
export const tintLabel = (name: string) => {
  const c = extTint(name);
  return c ? { color: c } : undefined;
};

// Source files → shiki language id. Unknown-but-textual extensions render as
// plain "text" (still a code element). Everything not listed falls back to
// download-with-filename at the call site (the #32 fix).
const CODE_LANG: Record<string, string> = {
  py: "python", js: "javascript", mjs: "javascript", cjs: "javascript",
  ts: "typescript", tsx: "tsx", jsx: "jsx", json: "json", jsonc: "jsonc",
  sh: "bash", bash: "bash", zsh: "bash", rb: "ruby", go: "go", rs: "rust",
  java: "java", kt: "kotlin", c: "c", h: "c", cpp: "cpp", cc: "cpp", hpp: "cpp",
  cs: "csharp", php: "php", swift: "swift", scala: "scala", lua: "lua", r: "r",
  sql: "sql", yaml: "yaml", yml: "yaml", toml: "toml", ini: "ini", css: "css",
  scss: "scss", less: "less", xml: "xml", dockerfile: "docker", makefile: "makefile",
};
const TEXT_EXTS = new Set(["txt", "text", "log", "env", "conf", "cfg", "properties"]);

// shiki language for a source file, or null if it isn't a code/text file.
export const codeLang = (name: string): string | null => {
  const e = ext(name);
  return CODE_LANG[e] ?? (TEXT_EXTS.has(e) ? "text" : null);
};

// Extensions the canvas renders inline (markdown, html, pdf, or any source file).
export const isRenderable = (name: string) =>
  isMd(name) || isHtml(name) || isPdf(name) || isImage(name) || isAudio(name) || isVideo(name) || isSpreadsheet(name) || is3d(name) || codeLang(name) != null;

// Trigger a name-preserving download from an authed blob URL. A bare blob URL
// carries no filename, so opening it instead saves with no extension — the
// corrupted-download bug. The download attribute restores name + extension.
export function saveBlob(url: string, name: string) {
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
}
