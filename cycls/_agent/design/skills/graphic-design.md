---
name: graphic-design
description: Single-frame visuals and sets of them — social posts, carousels, stories, posters, ads, banners, thumbnails, invitations, certificates, covers — sizes and safe areas, a copy budget, ten compositions with coordinates, Arabic posts, campaigns in several sizes; and how to make one in two or three calls (name every part, one render, one edit, never a guessed name).
---

# graphic-design — one frame, read in two seconds

Load `design-direction` with this skill for the look. This skill is the layout and the way of working.

## Sizes

| what | size | note |
|---|---|---|
| Instagram / LinkedIn feed post | `post-portrait` 1080 × 1350 | the most room in a feed: prefer it to square |
| square post | `square` 1080 × 1080 | |
| story / reel cover | `story` 1080 × 1920 | keep text out of the top 250 px and the bottom 320 px (the app's own bars) |
| X / Twitter, a link card | `x-post` 1600 × 900 | |
| LinkedIn banner | [1584, 396] | the profile photo covers the left ~400 px of the lower half on a profile |
| YouTube thumbnail | [1280, 720] | 3–5 words, a face or object, readable at 25% size |
| poster, flyer | `a4-poster` 1240 × 1754 | print: keep 60 px clear of every edge |
| invitation, certificate | [1754, 1240] (A4 landscape) or `a4-poster` | |
| slide-sized visual | `slide` 1920 × 1080 | |

## The copy budget

A visual is read, not studied. Count the words before the render:
- headline: up to 7 words (Arabic up to 6)
- one supporting line: up to 15 words
- CTA: 2–3 words, or a URL
- small print (date, place, handle): one line

If the user's text is longer, the rest goes in the caption you write with it, not on the image.

## Ten compositions (coordinates for 1080 × 1350, margin 96)

1. **Type poster**: the headline fills 80–90% of the width, set from y ≈ 300, and a small line plus CTA sit at
   the foot. Use it when the message is a few words.
2. **Photo + scrim**: a full-bleed image first, then a rect from y 600 to 1350 with fill
   `{"gradient": ["#00000000", "#000000d9"], "angle": 90}`, then a text stack anchored at the bottom
   (`"anchor": "bottom"`, y 1254). Use it for places, food, people and events.
3. **Split**: a photo over the top 55% (0, 0, 1080, 740) and a colour panel under it holding the copy, or
   left / right halves on a landscape frame. Use it for a product with an explanation.
4. **Hero object**: one 3D object (300–400 px) at the upper right, overlapping the headline's corner, with the
   headline flush left under it. Use it for a launch, a feature or a seasonal greeting. A 3D picture is a
   cut-out: give it no `shadow`, which draws a dark box around its square.
5. **Big number**: one figure at 300–420 px ("3×", "40%", "١٠٠٠") with its label under it in one line.
   Use it for results, milestones and offers.
6. **Glass card**: a texture or photo over the whole frame, and a card 96 px in (888 wide) with fill
   `#ffffff1a`, stroke `#ffffff33`, radius 40 and `"backdropBlur": 30` holding the copy. Use it for premium or tech.
7. **Framed**: an inset rect with only a `stroke` (48 px in) and centred copy inside. Use it for invitations,
   certificates, announcements and condolences.
8. **List post**: a title, then 3–5 rows of icon + short line (a horizontal stack per row, rows in a vertical
   stack, gap 28). Use it for tips, steps and "what's included".
9. **Quote card**: a giant quotation mark in the accent at 320 px and opacity 0.2, the quote at 56–64 px, then the
   name and role. Use it for testimonials and statements.
10. **Event**: a date block (day very large, month in small caps), the title, then time and place on one line and
   a QR (240 px) at the lower right. Use it for events, webinars and openings.

## Arabic

- Anchor right: a text box with `"align": "right"` and a `w`, placed with x = frameW − margin − w. A stack takes
  `"align": "end"`.
- Use an Arabic face (see `design-direction`), set ~10–15% larger than Latin would be, with no letterSpacing.
- Mirror the composition: the object goes on the left when the text is on the right.
- A bilingual post sets the Arabic line first and larger, with the English smaller beneath it, each in its own face.

## A carousel

`{"frames": [ … ]}` with every slide the same size (1080 × 1350). Export with `"format": "png"` to get one
image per slide. Plan it before the render:
- slide 1 is a hook (a question, a bold claim, a number) and says to swipe ("Swipe →" small, bottom right);
- the middle slides hold ONE point each, under the same grid, the same title position and the same small page
  marker ("02 / 07");
- the last slide is the takeaway plus a CTA.

Usually 5–8 slides. Every slide's text is one stack with ids (`"id": "s3-title"`), so a fix is an `edit` with
`frame` and that id.

## A campaign in several sizes

Use `pages`, one design with a page per size: `{"pages": [{"name": "Post", "size": "post-portrait", …}, {"name":
"Story", "size": "story", …}, {"name": "Banner", "size": [1584, 396], …}]}`. Lay out each page again for its
shape (a banner puts the headline beside the object, not under it). Never reuse one page's coordinates on another.

## Working fast: two or three calls for a post

1. **One render with everything in it**: the direction decided, every text in a stack, and an `id` on every
   node you might change (`headline`, `subline`, `cta`, `badge`, `hero`, `bg`). The ids you wrote are the names you
   edit by; never guess a name like `rect-27` or `text-8`. When you didn't name a part, `inspect` once and use
   the names it lists.
2. **Look at the image and the layout check**, then make ONE `edit` with all the fixes as a list of ops. Don't
   send one edit per op, and don't re-render: a new render makes a second file (`-2`) and loses hand edits.
3. **Another format** of the same design is `export`, not a render.

Wrong shapes that cost a refused call:
- `backdropBlur` and `blur` take a number (30), not `true`; `shadow` takes `true` or an object.
- An image needs `w` or `h` (a texture with neither fills the frame).
- A library picture is named with `asset`, never by a guessed path under attachments/assets/.
- An SVG logo goes in an svg node (`{"type": "svg", "src": "brand/logo.svg"}`), never an image node.
- A label ON a shape (a button, a badge, a date chip) is the shape, then a text with the SAME x, y, w, h and
  `"align": "center"`, `"valign": "center"`, both outside any stack. Never put them in a stack: it sets its
  children side by side or one under the next, never on top of each other, and a child's own x / y isn't read.
- A node may not START past the right or bottom edge. A word cut by the edge on purpose starts inside, or at a
  negative x / y, and is faint (alpha 30% or less, e.g. `#ffffff26`): the layout check leaves faint text alone.

## Example: a bold launch post, 1080 × 1350

```json
{"size": "post-portrait", "fill": "#ff4d00", "nodes": [
  {"type": "text", "id": "giant", "text": "LAUNCH", "x": -30, "y": 1020, "w": 1400, "size": 360, "font": "Anton",
   "color": "#ffffff26"},
  {"type": "image", "id": "hero", "asset": "rocket premium", "x": 660, "y": 96, "w": 330},
  {"type": "stack", "id": "copy", "x": 96, "y": 300, "w": 888, "gap": 30, "children": [
    {"type": "text", "id": "eyebrow", "text": "NEW · 21 OCTOBER", "size": 26, "letterSpacing": 6, "font": "Inter Bold", "color": "#1a0a00"},
    {"type": "text", "id": "headline", "text": "Ship in a day, not a quarter.", "size": 150, "lineHeight": 142,
     "font": "Anton", "color": "#ffffff"},
    {"type": "text", "id": "subline", "text": "Cycls turns a function into a product your customers can use.",
     "size": 34, "lineHeight": 48, "font": "Inter Medium", "color": "#1a0a00"}]},
  {"type": "rect", "id": "cta-pill", "x": 96, "y": 850, "w": 330, "h": 84, "radius": 42, "fill": "#1a0a00"},
  {"type": "text", "id": "cta", "text": "Start free", "x": 96, "y": 850, "w": 330, "h": 84, "valign": "center",
   "align": "center", "size": 32, "font": "Inter Bold", "color": "#ffffff"}
]}
```

## Example: an Arabic Ramadan post, 1080 × 1350

```json
{"size": "post-portrait", "fill": {"gradient": ["#0b1d3a", "#132c55"], "angle": 90}, "nodes": [
  {"type": "pattern", "id": "band", "asset": "moroccan", "color": "#d4af37", "opacity": 0.14, "x": 0, "y": 0, "w": 1080, "h": 300},
  {"type": "rect", "id": "band-rule", "x": 0, "y": 300, "w": 1080, "h": 3, "fill": "#d4af37"},
  {"type": "image", "id": "moon", "asset": "crescent moon", "x": 96, "y": 380, "w": 260},
  {"type": "stack", "id": "copy", "x": 304, "y": 700, "w": 680, "gap": 26, "align": "end", "children": [
    {"type": "text", "id": "headline", "text": "رمضان كريم", "size": 150, "lineHeight": 190, "font": "Reem Kufi Bold",
     "color": "#f5ecd7", "align": "right"},
    {"type": "text", "id": "subline", "text": "مواعيدنا في الشهر الفضيل: من التاسعة مساءً حتى الثالثة فجرًا",
     "size": 40, "lineHeight": 66, "font": "IBM Plex Sans Arabic", "color": "#d9cfb8", "align": "right"},
    {"type": "text", "id": "brand", "text": "بيت القهوة", "size": 34, "font": "IBM Plex Sans Arabic Bold",
     "color": "#d4af37", "align": "right"}]}
]}
```
