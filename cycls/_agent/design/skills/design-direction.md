---
name: design-direction
description: Choosing the look before the first render — the idea, a direction from real styles (editorial, Swiss, bold type, luxury, tech, warm, playful, Gulf heritage, corporate, quiet), its palette and type pair, and one signature detail — instead of one default recipe for everything. For any design: a post, a deck, a document. Also how to show two or three directions in one call.
---

# design-direction — decide the look, then render once

The tool's own DESIGN paragraph (a gradient, a big headline, one accent, a soft ellipse) is a floor, not a
style: used for everything, every design comes out looking the same. Before the first render of a piece, take
four decisions. Take them in your head, not as a message to the user, and with no extra call:

1. **The idea**: what the viewer should feel or do within two seconds, in one sentence ("Ramadan hours, felt
   as calm and generous").
2. **The direction**: the family below that fits the subject, the audience and the occasion. A brand kit
   fixes the colours and fonts, not the direction: composition, scale, imagery and the signature move stay yours.
3. **The system**: the palette (a ground, a text colour, ONE accent, at most one support colour), the type
   pair, the margin, and the left edges everything lines up on.
4. **The signature move**: the ONE detail someone would remember (list below). One, not three.

Then write all of it into the spec, and render once.

## Directions

Each gives where it fits, then its palette, type (Latin, then Arabic), composition and finish (the finish comes from the media library).

**Editorial**: food, culture, reports, thought leadership, premium services.
Palette: paper `#f5f0e8`, ink `#1c1917`, muted `#57534e`, accent terracotta `#b4532a` (or deep teal `#0f5257`).
Type: "Fraunces Bold" or "Playfair Display Bold" headlines, Inter or "DM Sans" text; one headline word in
"Fraunces Bold Italic". Arabic: "Amiri Bold" or "Markazi Text Bold" over "IBM Plex Sans Arabic".
Composition: flush left, a big serif headline, a thin rule, small letter-spaced caps above it, a lot of paper.
Finish: `"asset": "white paper texture"` over the paper colour at opacity 0.3.

**Swiss**: architecture, studios, conferences, schedules, anything that should look exact.
Palette: white or `#f2f2f0`, black `#111111`, ONE signal colour (red `#e63322` or cobalt `#1f3fff`).
Type: "Inter Black" or "Archivo Black" with Inter in one family of sizes that jump (220 / 44 / 22). Arabic: "Noto
Kufi Arabic Bold" with "IBM Plex Sans Arabic".
Composition: a strict grid, everything flush left, a huge word or number cut by the frame's edge, thin rules
between rows of facts.
Finish: none; the grid is the decoration.

**Bold type**: launches, sales, announcements, sport, any message of a few words.
Palette: one saturated ground (`#ff4d00`, `#ffd60a`, `#3a0ca3`, `#00a676`) with black or white, and no second accent.
Type: Anton, "Bebas Neue" or "Archivo Black" at 160–260 px, lineHeight ≈ 0.95 × size. Arabic: Lalezar, "Changa
Extra Bold" or "Alexandria Black", set ~15% larger than Latin to look the same size.
Composition: the headline IS the picture. It fills 80–90% of the width, with one small line and one CTA under it.
Finish: none, or one 3D object ("rocket premium") pushing into the headline's corner.

**Luxury**: perfume, jewellery, real estate, hotels, VIP invitations, a premium Ramadan.
Palette: near-black `#0e0e0e`, deep green `#0f2a24` or navy `#0d1b2a`, with champagne gold `#c9a45c` and text `#f5efe3`.
Type: "Cormorant Garamond Semi Bold" or "Bodoni Moda Bold" (large, never heavy) with "Montserrat Medium" in small
caps, letterSpacing 6–8. Arabic: "El Messiri Bold" or "Aref Ruqaa Bold" (calligraphic, for one short line) over Amiri.
Composition: centred and symmetrical, much empty dark space, thin gold rules, or an inset frame (a rect with
only a `stroke`, 40 px in from every edge).
Finish: "black marble texture" at low opacity, or one 3D object in "premium" (black and gold).

**Tech**: software, AI, fintech, product launches, developer events.
Palette: `#05070d` or `#0b1020`, text `#e6edf7`, muted `#7c8aa5`, ONE accent (cyan `#22d3ee` or violet
`#8b5cf6`), glows as radial gradients.
Type: "Space Grotesk Bold" or "Sora Bold" with Inter; numbers and labels in "JetBrains Mono Medium". Arabic:
"Readex Pro Bold" or "Noto Kufi Arabic Bold".
Composition: a dark field, one radial glow behind the focus, glass cards (fill `#ffffff14`, stroke `#ffffff26`,
`"backdropBlur": 30`), a product screenshot in a rounded box with a shadow.
Finish: none, or one "gradient" 3D icon.

**Warm & human**: health, education, food, community, NGOs, people and HR.
Palette: cream `#fff7ed`, terracotta `#c2410c`, olive `#5f6f52`, ink `#2b1d14`.
Type: "DM Serif Display" with "DM Sans". Arabic: "Almarai Extra Bold" over Almarai.
Composition: rounded shapes (radius 32+), photos of people, cards, generous spacing.
Finish: an illustration of people (an svg node, `"asset": "people"`), or a "fabric texture" at 0.3.

**Playful**: kids, consumer apps, delivery, events, a young audience.
Palette: two brights that fight a little (`#ffd60a` with `#3a0ca3`, or `#ff70a6` with `#70d6ff`) and white, never more.
Type: "Syne Extra Bold", "Bricolage Grotesque Extra Bold" or "Outfit Semi Bold". Arabic: "Lemonada Bold",
"Marhey Bold" or "Changa Extra Bold".
Composition: big rounded blocks, a sticker or badge turned a little (`"rotation": -6`), 3D emoji as characters.
Finish: one or two 3D emoji ("party popper", "star struck").

**Gulf heritage**: National Day, Founding Day, Ramadan, Eid, culture, tourism, coffee, dates, local food.
Palette: sand `#e9dcc3`, date brown `#4a2c1d`, Sadu red `#9b2226`, palm green `#2d6a4f`, gold `#b08d57`. For
National Day, the flag's green `#006c35` with white. For Ramadan nights: navy `#0b1d3a`, gold `#d4af37`, cream `#f5ecd7`.
Type: Arabic first. "Reem Kufi Bold", "El Messiri Bold" or "Aref Ruqaa Bold" (one short line) for display, with
"IBM Plex Sans Arabic" or Almarai for text. The Latin partner is "Cormorant Garamond Semi Bold" or "DM Serif Display".
Composition: right-anchored or centred, an ornament band (a pattern node in a strip of its own), generous space.
Finish: a pattern ("moroccan", "islamic") at 8–12% opacity, a museum ornament cropped to a band, or the
occasion's 3D object ("crescent moon", "mosque", "hot beverage"). Never one tagged `inscription` (it has
writing on it). The library has no dallah, fanous, palm or dates: "dates" finds a calendar.

**Corporate**: finance, consulting, B2B, government, results.
Palette: white, navy `#0b1f3a`, slate `#5b6b82`, one bright accent (`#1d4ed8` or `#0891b2`), surface `#eef2f8`.
Type: "Montserrat Bold" with "Open Sans", or "Plus Jakarta Sans" throughout. Arabic: "Tajawal Bold" with Tajawal,
or "IBM Plex Sans Arabic".
Composition: a clear grid, data forward (a stat, a chart), real photography, a colour band behind the title.
Finish: none.

**Quiet minimal**: wellness, fashion, architecture, a statement, "coming soon".
Palette: off-white `#f4f2ee` or stone `#e7e5e4`, ink `#1c1917`, one muted accent `#8a6e4b`.
Type: "Instrument Serif" (one line, large) with "Inter Medium" small. Arabic: "Markazi Text Bold" with
"IBM Plex Sans Arabic".
Composition: one small object or one line of type in a corner, 60%+ of the frame empty, nothing centred.
Finish: "plaster texture" at 0.25, or none.

**Choosing.** Take the feeling the brief names literally (premium → luxury, fun → playful, serious →
corporate, Swiss or editorial). The occasion outranks the industry: a bank's Ramadan post is Gulf heritage, in
the bank's colours. Young audiences take bold or playful, executives take corporate, Swiss or editorial. For an
Arabic audience, set the Arabic first and choose its face before the Latin one. Pieces that belong together (a
carousel, a campaign, one deck) share ONE direction; pieces that don't, shouldn't all share the same one.

**A deck or a document** takes its direction twice: as its `theme` (the palette and the type pair) and as its
`look`, how its slides or pages are composed. The look matters more, because two themes in one look are the same
layout recoloured. Editorial → `editorial`. Swiss → `swiss`. Bold type → `bold`. Luxury → `minimal` (or
`editorial`). Tech → `swiss` (or `bold` for a launch). Warm & human → `soft`. Playful → `soft` or `bold`. Gulf
heritage → `editorial` or `soft`. Corporate → `swiss` (or `classic` when the user wants it plain). Quiet minimal →
`minimal`. Always write the look out: without one, the tool guesses from the title, which is a fallback, not a
direction.

## Colour

- 60 / 30 / 10: the ground, the secondary areas, the accent. The accent marks the ONE thing to look at (a word,
  the button, a number), and nothing else.
- Body text needs at least 4.5 : 1 contrast with what is behind it. Light text on a photo needs a scrim.
- Dark is not black: `#0b0f19`, `#111111` and `#0e0e0e` read richer than `#000000`.
- A gradient runs between neighbouring hues (`#4f46e5` → `#7c3aed`) or one hue from light to dark, never a
  rainbow. A radial glow (the accent fading to transparent) behind the focus beats a flat field.
- Make tints of a colour with alpha (`#b4532a1f` for a card, a band) instead of adding new colours.
- With a photo, take the accent from the photo.

## Type

- Two families at most. The contrast between them does the work: a display serif over a sans, or one family in
  Black and Regular.
- Sizes jump: the headline is at least 3 × the body, and an eyebrow about a quarter of the headline.
- lineHeight: ≈ 1.0–1.1 × size on a headline, 1.4–1.5 × on body text, 1.6–1.7 × on Arabic body text.
- letterSpacing goes only on small Latin capitals (4–8). Never use it on Arabic. Huge Latin display type may go slightly tight (−1 to −3).
- Emphasis inside a headline is one word in the accent or in the display italic, written with `runs`.
- Arabic has no italics. An Arabic display face needs ~10–15% more size than Latin to read the same.

## Signature moves (pick ONE)

- **Cut by the edge**: an oversized word or number running off the frame (a negative `x`, or `x + w` past the
  width), set faint (`#ffffff26` on a dark or saturated ground, `#0000001a` on a light one). The layout check
  leaves text at 30% or less alone, so it is free to overlap and run off.
- **Highlight word**: one headline word in the accent or the italic, using `runs`.
- **One object**: a 3D object from the library overlapping the headline's corner (no `shadow`: on a cut-out it
  draws a dark box).
- **Inset frame**: a rect with only a `stroke` (1–2 px, gold or ink), 32–48 px in from every edge.
- **Glass card**: fill `#ffffff1a`, stroke `#ffffff33`, `"backdropBlur": 30`, over a photo or a glow.
- **Pattern band**: a pattern node in a strip (its own x / y / w / h) at 10–15%, under the headline or along one edge.
- **Duotone photo**: the photo, then a rect in the brand colour over it at opacity 0.55–0.7.
- **Turned badge**: a short word on a pill or circle — the text in the shape's box with `"valign": "center"` —
  and `"rotation": -8` on both.
- **Giant mark**: a quotation mark or numeral in the accent at 300+ px, behind the text at opacity 0.15 (faint, so unchecked).
- **Editorial header**: thin rules and small caps on one line ("ISSUE 04 —— RIYADH —— 2026").

## Show directions, not one guess

When the user asks for options, or the brief is open and the piece matters ("something for our launch"),
render two or three directions as the PAGES of one design, in ONE call: `{"pages": [{"name": "Editorial", …},
{"name": "Bold", …}, {"name": "Tech", …}]}`. Commit fully to each one, and make them differ in direction, not
only in colour. Ask which to take forward, then work on that page (`edit` with `page`) and `page_delete` the
rest. One render for three looks is cheaper than three renders and a conversation.

## Look before you present

The render comes back as an image. Check it against these:
- **Two seconds**: is the idea, and the headline, what's read first?
- **Template smell**: could any company's logo go on it? If so, push the scale or the signature move further.
- **The accent** is used once or twice, with nothing else competing.
- **Edges**: margins are equal, and the text shares one or two left edges.

Fix everything you find in ONE `edit` holding all the ops.

## A worked example: editorial post, 1080 × 1350

```json
{"size": "post-portrait", "fill": "#f5f0e8", "nodes": [
  {"type": "image", "id": "grain", "asset": "texture/ambientcg/paper001", "x": 0, "y": 0, "w": 1080, "h": 1350, "opacity": 0.35},
  {"type": "text", "id": "header", "text": "ISSUE 04  ———  RIYADH  ———  2026", "x": 96, "y": 96, "w": 888, "size": 22,
   "letterSpacing": 5, "font": "Inter Semi Bold", "color": "#57534e"},
  {"type": "stack", "id": "copy", "x": 96, "y": 330, "w": 860, "gap": 36, "children": [
    {"type": "text", "id": "headline", "font": "Fraunces Bold", "size": 132, "lineHeight": 136, "color": "#1c1917",
     "runs": [{"text": "Slow coffee, "}, {"text": "fast", "font": "Fraunces Bold Italic", "color": "#b4532a"},
              {"text": " mornings."}]},
    {"type": "rect", "id": "rule", "w": 120, "h": 4, "fill": "#b4532a"},
    {"type": "text", "id": "subline", "text": "Single-origin beans roasted every Sunday, at your door before seven.",
     "size": 36, "lineHeight": 52, "font": "Inter", "color": "#57534e"}]},
  {"type": "text", "id": "cta", "text": "qahwa.house/subscribe  →", "x": 96, "y": 1178, "w": 600, "size": 30,
   "font": "Inter Semi Bold", "color": "#1c1917"}
]}
```
