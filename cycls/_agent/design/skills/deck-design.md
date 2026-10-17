---
name: deck-design
description: Presentations that look designed — a theme made for the subject (built in, or your own palette and fonts on a base) and a look that composes it (editorial, swiss, bold, soft, minimal, classic), a rhythm of layouts and slide styles, action titles, which layout for which content, slot budgets, custom slides that keep the deck's grid, charts that make a point, speaker notes, Arabic decks; and how to make a whole deck in one render and change it without rendering again.
---

# deck-design — a deck is a sequence, not a pile of slides

Load `design-direction` with this skill to choose the look. The story comes first: what the audience must
leave with, and the slides that get them there. This skill turns that story into slides.

## The theme and the look

A deck has two decisions, and they are separate:
- the **theme** is its colours and faces;
- the **look** is how its slides are composed: where a title sits and how big it is, how a list, a number, a
  quote and a section slide are drawn.

Two decks in the same look with different themes are the same design recoloured. Most of the "this looks like
every other deck" comes from the look, not the colours, so choose it on purpose.

Built-in themes: `minimal-light`, `minimal-dark`, `bold-gradient`, `editorial`, `corporate`, `tech-dark`,
`warm`, `mono`, and `brand` (the workspace's brand kit, the default when one exists). Each fits a kind of subject:
- `corporate` for finance and B2B;
- `editorial` for culture, research and premium work;
- `tech-dark` for software and AI;
- `warm` for people, food and education;
- `mono` for architecture and design;
- `bold-gradient` for a launch or an event;
- `minimal-light` or `minimal-dark` when nothing else fits.

A theme is also an object that overrides ANY of a base's keys, so the direction you chose becomes the deck's own:
- colours: `bg`, `text`, `muted` (content slides); `hero`, `heroText`, `heroMuted`, `heroAccent` (title,
  section and closing slides — `hero` may be a gradient); `accent`, `accent2`, `onAccent`; `surface` (cards,
  table bands), `line` (rules);
- type: `heading`, `body`, `arHeading`, `arBody`;
- `decor`: `glow`, `rule`, `bar`, `circles` or `none` (the deck's one motif); `radius` (corners).

Set the colours and fonts of the direction, not only the accent: a deck that differs only in its accent still
looks like every other deck.

The looks (`"look"` in the deck, beside `theme`):
- `editorial`: a running head over a hairline at the top of each slide, large titles, points as numbered rows
  between rules, figures set as type under a rule, a centred quote, the title slide's title huge at its foot.
  For research, culture, strategy, premium services.
- `swiss`: each slide's title in a column of its own at the left with the content beside it, a heavy rule over
  both, points as columns under big numbers, "4 / 12" page numbers, a giant section number. For architecture,
  design, engineering, anything that should look exact.
- `bold`: big titles, the accent laid on as fields: points and figures on accent tiles, the second column on the
  accent, section and quote slides flooded with it, a split title slide. For launches, sales, events, a pitch.
- `soft`: centred titles with a pill eyebrow, points and figures on rounded cards, timeline steps as cards, the
  section number in a disc. For education, health, community, consumer products.
- `minimal`: small titles, wide margins, hairlines, no fills, title and section slides on the paper instead of
  the dark colour. For luxury, fashion, architecture, a quiet statement.
- `classic`: titles at the head, a bulleted list, figures on dividers. The plain default.

Without a `look`, the deck takes its theme's (editorial → editorial, tech-dark → swiss, warm → soft, mono →
minimal, bold-gradient → bold, any other → classic), so a custom theme on `minimal-light` or `corporate`, or the
brand kit, comes out classic unless you choose. Match the look to the direction (`design-direction`), and don't
give every deck the same one: the next deck on another subject should look different.

Decide the theme and the look before the render, because changing them later means rendering the whole deck
again.

## Rhythm

- Open on `title`. Use an `agenda` for 10+ slides, and a numbered `section` slide every 3–5 content slides in a
  long deck. End on `closing`, with its `cta`, `contact` or `qr`.
- Change the layout every slide or two. Never put three `bullets` slides in a row. For every two slides of text,
  give one of picture, number or chart (`image-left` / `image-right`, `image`, `stats`, `chart`, `quote`).
- Vary how slides of one kind are drawn with a slide's `style`, so two `bullets` slides don't look alike:
  - `bullets`: `list`, `rows`, `numbers`, `cards` or `plain`;
  - `stats`: `dividers`, `ruled`, `tiles` or `plain`;
  - `two-column`: `cards`, `ruled` or `contrast`;
  - `quote`: `mark`, `center`, `big`, `panel` (on the accent) or `card`;
  - `agenda`: `list`, `rows` or `tiles`;
  - `timeline`: `line`, `ruled` or `steps`;
  - `table`: `band`, `rules` or `soft`.

  The look sets each kind's style. Override it for one or two beats, not on every slide: a `panel` quote in an
  editorial deck, the key points as `cards` once.
- **Action titles**: a content slide's title states its conclusion, so a reader of the titles alone gets the
  story ("Churn fell 40% after the new onboarding", not "Churn").
- One idea per slide. A slide that needs two titles is two slides.

## Which layout

| the content | layout |
|---|---|
| a claim and its 3–5 reasons | `bullets` (with `image` when there's a picture for it) |
| a concept and its example, a product and its picture | `image-left` / `image-right` |
| 1–4 numbers that matter | `stats` |
| a trend, a comparison, a share | `chart` (with `takeaway`) |
| before / after, us / them, problem / solution | `two-column` |
| a plan, a history, steps with dates | `timeline` (2–6) |
| a detailed comparison | `table` (≤ 7 rows, ≤ 5 columns) |
| a customer's or an expert's words | `quote` |
| an emotional beat, a place, the product in use | `image` (full-bleed photo, a short title) |
| who is behind it | `team` (≤ 8) |
| the room's opinion | `poll` (live votes from phones) |
| a process, a diagram, a matrix, one huge statement | `custom` |

Slot budgets, so nothing is shrunk:
- a title: up to 8 words, two lines at most;
- bullets: 3–5, each up to 12 words;
- a stat value: short ("3.2×", "40%", "SAR 12M"), with a label of up to 6 words;
- a timeline item: a short date and a 2–4 word title;
- a quote: up to 30 words.

## Pictures

A slide's `image` is a workspace path, `{"stock": "…"}` or `{"asset": "…"}`. Stock queries are specific: "barista
pouring milk latte art close up", not "coffee". A `title` slide with an `image` is a full-bleed photo with a scrim
over it. Use one photographic world across the deck (all warm interiors, or all aerial cities), not a different
mood on every slide.

## Custom slides

`{"layout": "custom", "fill": "#…", "nodes": [ … ]}` is a frame you place by hand, and it gets no decor, footer
or page number. Keep the deck's grid so it doesn't look pasted in. On a 1920 × 1080 slide the margins are 144 and
1776, the content stays above y 950, and the title is in the theme's heading font, placed as the look places it:
- `classic`: the title at y 92, 64 px; with `decor: "rule"`, a 2 px rule in the `line` colour at y ≈ 222;
- `editorial`: a running head — the footer text in 20 px capitals (`letterSpacing` 4, the `muted` colour) at
  y 49 — over a 2 px `line` rule at y 87; the title at y 132, 80 px;
- `swiss`: a 5 px rule in the text colour at y 58 from 144 to 1776; the title in the column x 144, w 490 from
  y 92, 54 px; the content in x 706 to 1776, from y 92;
- `bold`: the title at y 92, 88 px; `soft`: centred (x 144, w 1632, `"align": "center"`) at y 92, 64 px;
- `minimal`: margins 192 and 1728, the title at y 119, 52 px.

Use the theme's colours, written out.

Put an `id` on every node. Good uses:
- a process: 3–4 cards in a row, with `line` connectors (`"end": "arrow"`);
- a 2 × 2 matrix: rects with their labels;
- a single huge statement: 120–160 px, one line of support.

## Charts

- column: categories compared;
- line or area: a trend over time;
- bar: long category names;
- donut: shares of a whole, 5 parts or fewer;
- stacked: composition over time.

Use `"values": true` when the exact numbers matter. A `takeaway` (`{value, text}`) says what the chart proves:
the one number and its meaning. The chart's colours come from the theme's accents.

## Notes and Arabic

- Speaker `notes` on every content slide: 2–4 sentences of what to SAY, not what the slide already shows.
- An Arabic deck is laid out right to left by itself. Give it `arHeading` / `arBody` in the theme for its
  direction ("Reem Kufi Bold", "IBM Plex Sans Arabic"). An Arabic-first bilingual deck takes `"dir": "rtl"`.

## Working fast

1. **One render for the whole deck**: theme, every slide, notes and footer. Never build it slide by slide.
   Use `"format": "pptx"` when it will be presented or edited in PowerPoint; other formats come later from `export`.
2. **Every slide comes back to you.** Fix what's off without rendering again:
   - wording or style on a slide: ONE `edit`, ops with `frame` (the slide index from 0) and the node's name
     (layouts name their parts: `title`, `subtitle`, `eyebrow`, `stat-1` …; `inspect` lists them);
   - a slide rebuilt: `update_slide` {number from 1, slide};
   - notes only: `update_slide` {number, notes};
   - structure: `add_slide`, `move_slide`, `duplicate_slide`, `delete_slide`.
3. **Another format** of the same deck (PDF, images) is `export`, not a render.

## Example: a six-slide deck in its own theme

```json
{"deck": {
  "theme": {"base": "editorial", "bg": "#f6f1e7", "text": "#2b1d14", "muted": "#6b5b4b", "hero": "#3b2416",
            "heroText": "#f6f1e7", "heroMuted": "#d8c7ad", "heroAccent": "#d4af37", "accent": "#9b2226",
            "accent2": "#2d6a4f", "surface": "#ece3d3", "line": "#d9ccb6", "heading": "DM Serif Display",
            "body": "DM Sans", "arHeading": "Reem Kufi Bold", "arBody": "IBM Plex Sans Arabic", "decor": "rule", "radius": 6},
  "look": "editorial",
  "footer": {"text": "Qahwa House · Investor update"},
  "slides": [
    {"layout": "title", "eyebrow": "INVESTOR UPDATE · Q3 2026", "title": "Specialty coffee, now in every district of Riyadh",
     "subtitle": "Where we are, and where the next round takes us", "notes": "Thank everyone; one line on why we are here."},
    {"layout": "stats", "title": "A quarter of firsts", "items": [{"value": "14", "label": "branches open"},
     {"value": "38%", "label": "growth on Q2"}, {"value": "4.8", "label": "average rating"}],
     "notes": "Fourteen branches, growth well ahead of plan, and customers who rate us higher than any rival."},
    {"layout": "chart", "title": "Subscriptions overtook walk-ins in August",
     "chart": {"kind": "line", "data": {"labels": ["Apr", "May", "Jun", "Jul", "Aug", "Sep"],
       "series": [{"name": "Subscriptions", "values": [210, 260, 330, 420, 560, 690]},
                  {"name": "Walk-ins", "values": [480, 470, 500, 510, 520, 530]}]}},
     "takeaway": {"value": "3.3×", "text": "subscriptions since April"},
     "notes": "The crossing point is the story: a recurring business, not a café chain."},
    {"layout": "custom", "fill": "#f6f1e7", "nodes": [
      {"type": "text", "id": "running-head", "text": "QAHWA HOUSE · INVESTOR UPDATE", "x": 144, "y": 49, "w": 1200,
       "size": 20, "letterSpacing": 4, "font": "DM Sans Semi Bold", "color": "#6b5b4b"},
      {"type": "rect", "id": "head-rule", "x": 144, "y": 87, "w": 1632, "h": 2, "fill": "#d9ccb6"},
      {"type": "text", "id": "title", "text": "How a bag reaches a door in 36 hours", "x": 144, "y": 132, "w": 1632,
       "size": 80, "font": "DM Serif Display", "color": "#2b1d14"},
      {"type": "rect", "id": "card-1", "x": 144, "y": 380, "w": 440, "h": 300, "radius": 6, "fill": "#ece3d3"},
      {"type": "rect", "id": "card-2", "x": 740, "y": 380, "w": 440, "h": 300, "radius": 6, "fill": "#ece3d3"},
      {"type": "rect", "id": "card-3", "x": 1336, "y": 380, "w": 440, "h": 300, "radius": 6, "fill": "#ece3d3"},
      {"type": "line", "id": "arrow-1", "from": [600, 530], "to": [724, 530], "color": "#9b2226", "width": 4, "end": "arrow"},
      {"type": "line", "id": "arrow-2", "from": [1196, 530], "to": [1320, 530], "color": "#9b2226", "width": 4, "end": "arrow"},
      {"type": "stack", "id": "step-1", "x": 192, "y": 428, "w": 344, "gap": 18, "children": [
        {"type": "text", "id": "step-1-n", "text": "01", "size": 30, "font": "DM Sans Bold", "color": "#9b2226"},
        {"type": "text", "id": "step-1-t", "text": "Roasted on order", "size": 40, "font": "DM Serif Display", "color": "#2b1d14"},
        {"type": "text", "id": "step-1-x", "text": "Sunday and Wednesday, in our Al Olaya roastery.", "size": 26, "lineHeight": 38, "color": "#6b5b4b"}]},
      {"type": "stack", "id": "step-2", "x": 788, "y": 428, "w": 344, "gap": 18, "children": [
        {"type": "text", "id": "step-2-n", "text": "02", "size": 30, "font": "DM Sans Bold", "color": "#9b2226"},
        {"type": "text", "id": "step-2-t", "text": "Packed by hand", "size": 40, "font": "DM Serif Display", "color": "#2b1d14"},
        {"type": "text", "id": "step-2-x", "text": "Rested 24 hours, sealed with the roast date.", "size": 26, "lineHeight": 38, "color": "#6b5b4b"}]},
      {"type": "stack", "id": "step-3", "x": 1384, "y": 428, "w": 344, "gap": 18, "children": [
        {"type": "text", "id": "step-3-n", "text": "03", "size": 30, "font": "DM Sans Bold", "color": "#9b2226"},
        {"type": "text", "id": "step-3-t", "text": "At the door", "size": 40, "font": "DM Serif Display", "color": "#2b1d14"},
        {"type": "text", "id": "step-3-x", "text": "Our own riders, before seven in the morning.", "size": 26, "lineHeight": 38, "color": "#6b5b4b"}]}],
     "notes": "Three steps, all ours. That control is why the rating holds as we grow."},
    {"layout": "quote", "style": "panel", "quote": "It is the first coffee subscription that tastes like the café.",
     "author": "Noura Al-Harbi", "role": "Subscriber since March", "notes": "Read it, pause."},
    {"layout": "closing", "title": "Fourteen districts down, forty to go", "subtitle": "Raising SAR 12M to open the next 26 branches",
     "cta": "Read the plan", "contact": "invest@qahwa.house", "notes": "The ask, then questions."}]}}
```
