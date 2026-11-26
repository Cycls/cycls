// A chart or a flowchart taken out of the chat: a picture (PNG, twice the size), its numbers (CSV), or a file in the
// workspace. The picture draws its words with the page's own fonts: an SVG drawn as an image can't load them.
import { dirOf } from "../../lib/bidi";
import { saveBlob } from "../canvas-utils";

export const fileName = (s: string | undefined, fallback: string) =>
  (s || fallback).replace(/[\\/:*?"<>|\n]+/g, " ").trim().slice(0, 80) || fallback;

export function download(data: Blob, name: string) {
  const url = URL.createObjectURL(data);
  saveBlob(url, name);
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/** Rows as a CSV Excel opens in Arabic too (a BOM), every cell quoted where it needs to be. */
export const csv = (rows: (string | number)[][]) =>
  new Blob(["﻿" + rows.map((r) => r.map((v) => (/[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : v)).join(",")).join("\r\n")],
           { type: "text/csv;charset=utf-8" });

type Words = { title?: string; subtitle?: string; legend?: { name: string; color: string }[]; source?: string };

/** The drawing as a PNG: its title and subtitle over it, its legend and source under it, in the page's colors. */
export async function picture(svg: SVGSVGElement, words: Words, scale = 2): Promise<Blob> {
  const box = svg.getBoundingClientRect(), page = getComputedStyle(svg.closest("figure") || svg);
  const copy = svg.cloneNode(true) as SVGSVGElement;
  const from = [svg, ...svg.querySelectorAll("*")], to = [copy, ...copy.querySelectorAll("*")];
  const texts: { el: Element; style: CSSStyleDeclaration }[] = [];
  from.forEach((el, i) => {
    const cs = getComputedStyle(el), s = (to[i] as SVGElement).style;
    for (const p of ["fill", "stroke"]) { const v = cs.getPropertyValue(p); if (!v.startsWith("url(")) s.setProperty(p, v); }
    for (const p of ["opacity", "stroke-width", "stroke-dasharray", "fill-opacity", "stroke-opacity"]) s.setProperty(p, cs.getPropertyValue(p));
    s.setProperty("animation", "none");
    s.setProperty("transition", "none");
    if (el.tagName === "text" && !el.querySelector("tspan") || el.tagName === "tspan") texts.push({ el, style: cs });
  });
  copy.querySelectorAll("text").forEach((t) => t.remove());   // drawn below in the page's fonts
  copy.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  copy.setAttribute("width", String(box.width));
  copy.setAttribute("height", String(box.height));
  const art = new Image();
  const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(copy)], { type: "image/svg+xml;charset=utf-8" }));
  await new Promise((ok, fail) => { art.onload = ok; art.onerror = fail; art.src = url; });
  URL.revokeObjectURL(url);

  const pad = 24, font = page.fontFamily, ink = page.color, muted = getComputedStyle(document.documentElement).getPropertyValue("--color-muted-foreground") || ink;
  const head = (words.title ? 24 : 0) + (words.subtitle ? 20 : 0) + (words.title || words.subtitle ? 12 : 0);
  const foot = (words.legend?.length ? 30 : 0) + (words.source ? 22 : 0);
  const W = box.width + pad * 2, H = head + box.height + foot + pad * 2;
  const canvas = document.createElement("canvas");
  canvas.width = W * scale;
  canvas.height = H * scale;
  const ctx = canvas.getContext("2d")!;
  ctx.scale(scale, scale);
  ctx.fillStyle = page.backgroundColor && page.backgroundColor !== "rgba(0, 0, 0, 0)" ? page.backgroundColor : "#fff";
  ctx.fillRect(0, 0, W, H);
  const line = (text: string, y: number, size: number, weight: number, color: string) => {
    const rtl = dirOf(text) === "rtl";
    ctx.font = `${weight} ${size}px ${font}`;
    ctx.fillStyle = color;
    ctx.direction = rtl ? "rtl" : "ltr";
    ctx.textAlign = rtl ? "right" : "left";
    ctx.fillText(text, rtl ? W - pad : pad, y);
  };
  let y = pad;
  if (words.title) { line(words.title, y + 16, 15, 600, ink); y += 24; }
  if (words.subtitle) { line(words.subtitle, y + 14, 12, 400, muted); y += 20; }
  if (head) y += 12;
  ctx.drawImage(art, pad, y, box.width, box.height);
  ctx.textBaseline = "middle";
  ctx.textAlign = "center";
  for (const { el, style } of texts) {
    const r = el.getBoundingClientRect();
    if (!r.width || !el.textContent) continue;
    ctx.font = `${style.fontWeight} ${style.fontSize} ${font}`;
    ctx.fillStyle = style.fill;
    ctx.direction = dirOf(el.textContent) === "rtl" ? "rtl" : "ltr";
    ctx.fillText(el.textContent, pad + r.left - box.left + r.width / 2, y + r.top - box.top + r.height / 2);
  }
  ctx.textBaseline = "alphabetic";
  y += box.height;
  if (words.legend?.length) {
    ctx.font = `400 12px ${font}`;
    const items = words.legend.map((l) => ({ ...l, w: ctx.measureText(l.name).width + 26 }));
    let x = W / 2 - items.reduce((a, l) => a + l.w, 0) / 2;
    for (const l of items) {
      ctx.fillStyle = l.color;
      ctx.beginPath();
      ctx.roundRect(x, y + 14, 10, 10, 2);
      ctx.fill();
      ctx.fillStyle = muted;
      ctx.direction = dirOf(l.name) === "rtl" ? "rtl" : "ltr";
      ctx.textAlign = ctx.direction === "rtl" ? "right" : "left";
      ctx.fillText(l.name, ctx.direction === "rtl" ? x + l.w - 4 : x + 14, y + 23);
      x += l.w;
    }
    y += 30;
  }
  if (words.source) line(words.source, y + 16, 11, 400, muted);
  return await new Promise<Blob>((ok, fail) => canvas.toBlob((b) => (b ? ok(b) : fail(new Error("no picture"))), "image/png"));
}
