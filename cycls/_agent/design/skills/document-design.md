---
name: document-design
description: PDFs that read well and look made — reports, proposals, white papers, user guides and manuals, newsletters, brochures, CVs, letters, invoices — the settings each kind takes (cover, openers, columns, contents, page count), the theme as your own palette and fonts and the look that composes the pages (editorial, swiss, bold, soft, minimal, classic), which block for which content, screenshots and figures, a page budget; and how to build a long document in few calls and change it by section, without the hand-edit hold.
---

# document-design — content that flows over pages

Load `design-direction` with this skill to choose the look. A document is written, not placed: you send the
content in order, and the pages make themselves. Your craft is choosing the settings for the kind of document,
and the block for each kind of content.

## This PDF is theirs

There is no house PDF. Read the brief the way you listen to a piece of music: its mood, its pace, who it is for, what it
wants to feel like. Then invent the page for it. Their words come first: anything they name, you do exactly.

One thing is settled, because people asked for it: the text sits at the page's normal edge, across its width, in plain
alignment, unless they ask otherwise (`"align": "justify"`, `"measure": "set-in" | "hang" | "narrow" | "center"`,
`"paragraphs": "indent"`).

Everything else is a tool, and no tool is a default. `"lines": true`; `"headings": {"weight", "size": "small" | "regular" |
"large", "caps": true, "color": "ink" | "accent"}`; a look; a cover or none; `openers`; a block's `style`; numbers or none;
photos; `columns`; a hand-built area (`nodes`) or a hand-built page (`pages`). Use any of them or none, because this piece
calls for it. Having no lines is as much a habit as having them, and so is a light title or a bold one. What the last PDF
did is the reason not to do it again: the recent designs list what each one chose.

## What each kind has to hold

This is what the content needs. How it looks is yours to invent for this brief.

| kind | what it holds |
|---|---|
| report, annual review | contents (automatic past three sections); `"numbering": true` with several charts |
| proposal, offer | pricing as a `table`; terms as `numbered`; a way to answer (`contact`, a `back` page) |
| white paper, research | `footnotes`; `"figures": true` when it has many charts |
| user guide, manual, how-to | each section is one task; steps as `numbered`; screenshots as `image` with `"fit": "contain"`; warnings as `callout` tone `warning` |
| newsletter, bulletin | short sections that run on (`"break": "none"`) |
| brochure, company profile | `pairs` for facts; contact and a QR on a `back` page |
| CV | `"max_pages": 1` (or 2), `kind`, `meta` (the contact line); experience as `h3` + `aside` (the dates) + `bullets` |
| letter, memo | `"cover": false`, `kind` "Letter", the body as `p` |
| invoice, quotation | `"cover": false`, `pairs` (to / from / number / date), a `table` of lines, the total where it can't be missed |

## Pages you compose yourself

Not every PDF is text that flows. An activity book, a worksheet, a planner, a certificate, a menu, a programme, an
invitation or a poster is composed page by page: `{"frames": [{"size": [1240, 1754], "fill": …, "nodes": […]}, …]}`, one
frame a page (A4 at 150 dpi; `[1275, 1650]` for US Letter). It is one Cycls Design file: it opens in the editor, stays
editable, and downloads as a PDF. Never leave Design for a script or HTML to get a page like this. Nothing on it is out of reach:

- a curve, a wave, a torn edge, any shape that runs off the page: `svg` with a `path`;
- a box to draw in, a sticker spot, a coupon edge: `rect` or `ellipse` with `"dash": [on, off]`;
- a line to write on: `line` with `from`, `to` and `"dash"` (`[2, 7]` reads as dots);
- things to count, match, colour or spot: `icon`, repeated, from any Iconify set;
- a word search, crossword, calendar, bingo card or timetable: a grid of `rect` and `text`. Work a puzzle out with `bash`
  first, so every word is really in it and the answer is right;
- text meant to be faint, letters to trace or a watermark: `"asked": true` on it, so the layout check keeps its colour.

These are materials. Which of them this piece uses, and what it looks like, comes from its subject and who it is for.

Paper: `"size": "a4"` (default), `"letter"` for the US, `"a5"` for a booklet, `"landscape": true` for a
dashboard-like report.

## The theme

Built-in themes: `editorial`, `corporate`, `minimal-light`, `minimal-dark`, `tech-dark`, `warm`, `mono`,
`bold-gradient`, and the brand kit by default. They are BASES: one used as it stands looks like every document made
from it. A theme is an object of overrides on a base, which is how the palette and faces you chose
(design-direction) become the document's. A new document's cover and back draw no `glow` or `circles` unless the
theme writes `"decor"` in, and the concept should give the cover its own idea instead. Its keys: `{"base", "bg", "surface", "line", "accent",
"hero", "heroAccent", "heading", "body", "arHeading", "arBody"}`, each one chosen for this piece.
- `hero` paints the cover, the bands and the chapter pages.
- `accent` paints the rules, numbers and links.
- `surface` paints the callouts and table bands.

## The look

The theme is the colours and faces; the `look` is how the pages are composed. It is the larger half of what makes
one PDF not look like the last: the measure and the margins, how a section opens, and what a heading, a callout,
a quote, a figure, a card and a table look like.
- `editorial`: a section opens with its number in small capitals; quotes are large; stats and cards are unfilled;
  tables have no header fill.
- `swiss`: a large section number over its title; nothing filled.
- `bold`: the text a little larger; each section opens on a field of the accent
  with its number large; h2s in the accent; stats on accent tiles, callouts filled, cards on the theme's dark
  colour, tables with an accent header.
- `soft`: the section's number on a pill; callouts as rounded panels with an icon;
  quotes and stats on rounded cards; cards with their icon in a tinted disc.
- `minimal`: wide margins; small-capital h2s; outlined callouts and cards; quotes in
  italic; no running head, the page number centred.
- `classic`: numbered openers; callouts, stats and cards on the surface.

A look without a `cover` style gives its own. No kind of document has a look of its own: choose it for this brief, and
give the cover, the openers and the blocks their own styles when that makes a better piece than the look's set.

`"openers": "band"` and `"page"` open a section the same way in every look; the default, `"plain"`, is the one
the look draws. With a look other than classic, leave `openers` out unless the document wants chapter pages.

A callout, quote, stats, cards or table block takes `style` to be drawn another way than its look, for one or
two moments that should stand out:
- `callout`: `box`, `rules`, `top`, `fill`, `soft` or `outline`;
- `quote`: `bar`, `pull`, `big`, `card` or `plain`;
- `stats`: `cards`, `ruled`, `tiles` or `plain`;
- `cards`: `fill`, `ruled`, `dark`, `soft` or `outline`;
- `table`: `band`, `rules`, `accent` or `zebra`.

## Blocks: which for what

| the content | block |
|---|---|
| a section's opening finding | `lead` (one paragraph, the conclusion first) |
| 2–4 headline numbers | `stats` |
| a trend or comparison | `chart` with a `title` and a `caption` that says what it shows |
| exact figures | `table` (≤ 8 columns; long tables run over pages by themselves) |
| one thing the reader must not miss | `callout` (tone `key`, `info` or `warning`), at most one a section |
| three parallel ideas, services, features | `cards` (with an Iconify `icon`, e.g. "lucide:shield-check") |
| facts as label / value | `pairs` |
| a person's words | `quote` with `by` |
| two things side by side | `columns` |
| a definition, a date, a source next to a paragraph | `aside` on the `p` (small print under it; beside it with a `measure` that leaves a margin) |
| where a number comes from | `note`, or a `[^key]` footnote |
| a diagram the blocks can't make | `nodes` with `h`: a hand-built area in the flow |

## Pictures

- A photo is cropped to a band.
- A screenshot or diagram must be shown whole: `"fit": "contain"`, with `"width": "text"` for a narrower one.
- Give every figure a `caption`.
- Photos come from a workspace path, `{"stock": "…"}` or `{"asset": "…"}`.
- A guide's screenshots go into the workspace first, then in as `image` blocks, one per step that needs it, not
  one per paragraph.

## Page budget

An A4 page holds about 400–450 words of body text in one column, less with headings. A chart or a photo takes
about a third of a page, and a `stats` row about a sixth. Work out the pages before the render, and set
`max_pages` when the user names a count: the type then steps down to fit (to 85%), and the reply says if it
still doesn't.

## Writing that reads

- Each section opens with what it found: a `lead`, then the evidence.
- Paragraphs run 2–4 sentences. Bold a phrase only where a reader truly needs it, never as a habit.
- Use real numbers, with units and dates.
- A heading says what the section says ("Costs fell in every region"), not its topic ("Costs").

## Working fast, and the hand-edit hold

1. **One render** carries the whole document when it fits a call. A very long one: render the first sections,
   then `add_section` for each of the rest, one call each, in order.
2. **Change content through the document, not through its pages**: `update_section` {name, number, section}
   with only what changes, `add_section`, `move_section`, `delete_section`, and `update_document` for the title,
   theme or cover. Each lays the pages out again from the source.
3. **`edit` on a page comes last.** It changes that page's nodes but not the source. The next section change
   lays the pages out from the source and would drop the edit, so the tool refuses it ("not rendered — … pages
   were changed after it was last rendered"). Make every content change through the sections first, and keep
   page `edit`s for final touches once the content is settled. When the hold does come:
   - put the edited wording into the section you send;
   - tell the user what can't be kept;
   - call again with `"discard_edits": true`.
   Never send the same call again unchanged, and never run several section changes in parallel on one document.
4. **The pages come back to you**: check what they say and how it is set out (the polish pass in
   `design-direction`). What you find is a section change, not a page `edit`.
5. **Another format** is `export`; a new render under a new name is never how to change a document.

## Example: a short report

```json
{"document": {
  "title": "City coffee market 2026", "subtitle": "Where specialty coffee grows next", "author": "Corner Roast strategy team",
  "date": "October 2026", "organization": "Corner Roast",
  "theme": {"base": "editorial", "bg": "#ffffff", "surface": "#eef3f2", "line": "#d5e0de", "accent": "#0f5257", "hero": "#10302f", "heroAccent": "#e9c46a",
            "heading": "Fraunces Bold", "body": "Source Serif 4"},
  "look": "editorial", "cover": {"style": "full", "eyebrow": "MARKET REVIEW"},
  "sections": [
    {"title": "Specialty coffee doubled in three years", "blocks": [
      {"lead": "Specialty coffee is now a third of the city's café spend, up from a sixth in 2023, and the growth has moved from the centre to the new districts in the north and east."},
      {"stats": [{"value": "SAR 4.1B", "label": "café spend, 2026"}, {"value": "34%", "label": "specialty share"}, {"value": "2.1×", "label": "growth since 2023"}]},
      {"chart": {"kind": "column", "data": {"labels": ["2023", "2024", "2025", "2026"],
        "series": [{"name": "Specialty share (%)", "values": [17, 22, 29, 34]}]}, "values": true, "suffix": "%"},
       "title": "Specialty share of café spend", "caption": "The share doubled; most of the gain came after 2024."},
      "Three things drove it: a younger customer who chooses by origin and roast, delivery that made a good cup available outside the centre, and rents in the new districts that let small roasters open a first branch."]},
    {"title": "The next districts", "blocks": [
      {"lead": "Four districts have the demand and too few specialty cafés to meet it."},
      {"table": {"columns": ["District", "Households", "Specialty cafés", "Cafés per 10k"],
        "rows": [["Al Narjis", "41,000", "6", "1.5"], ["Al Arid", "28,000", "3", "1.1"], ["Qurtubah", "35,000", "7", "2.0"], ["Al Yasmin", "52,000", "14", "2.7"]]},
       "title": "Households and specialty cafés by district", "caption": "Under two cafés per 10,000 households marks a gap."},
      {"callout": {"title": "Recommendation", "text": "Open in Al Narjis and Al Arid first: the deepest gaps, and rents a third below Al Yasmin's.", "tone": "key"}, "style": "fill"},
      {"note": "Sources: national household survey 2025; Corner Roast café census, September 2026."}]}]}}
```
