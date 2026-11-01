---
name: document-design
description: PDFs that read well and look made — reports, proposals, white papers, user guides and manuals, newsletters, brochures, CVs, letters, invoices — the settings each kind takes (cover, openers, columns, contents, page count), the theme as your own palette and fonts and the look that composes the pages (editorial, swiss, bold, soft, minimal, classic), which block for which content, screenshots and figures, a page budget; and how to build a long document in few calls and change it by section, without the hand-edit hold.
---

# document-design — content that flows over pages

Load `design-direction` with this skill to choose the look. A document is written, not placed: you send the
content in order, and the pages make themselves. Your craft is choosing the settings for the kind of document,
and the block for each kind of content.

## Settings by kind

| kind | settings | looks that suit it |
|---|---|---|
| report, annual review | `cover` full (or split with a photo), `"openers": "band"`, contents (automatic past three sections), `"numbering": true` with several charts | editorial, bold, classic |
| proposal, offer | `cover` split with a photo of the client's world; a `back` page with `title`, `text`, `contact`; pricing as a `table`; terms as `numbered` | bold, swiss |
| white paper, research | `cover` type; `"openers": "page"` with each section's `summary`; `footnotes`; `"figures": true` when it has many charts | editorial, swiss |
| user guide, manual, how-to | `cover` band or type; `"openers": "page"`; each section is one task; steps as `numbered`; screenshots as `image` with `"fit": "contain"`; warnings as `callout` tone `warning` | swiss, soft |
| newsletter, bulletin | `"columns": 2` (3 for a dense bulletin), `cover` band; short sections that run on (`"break": "none"`) | editorial, soft |
| brochure, company profile | `cover` full with a photo; `cards` and `stats`; `pairs` for facts; a `back` page with contact and a QR | bold, soft |
| CV | `"cover": false`, `"max_pages": 1` (or 2), `kind`, `meta` (the contact line); experience as `h3` + `aside` (the dates) + `bullets`; skills as `pairs` | swiss, minimal, editorial |
| letter, memo | `"cover": false`, `"theme": "mono"` or the brand, `kind` "Letter", the body as `p` | minimal |
| invoice, quotation | `"cover": false`, `pairs` (to / from / number / date), a `table` of lines, a `callout` tone `key` for the total | swiss, classic |

Paper: `"size": "a4"` (default), `"letter"` for the US, `"a5"` for a booklet, `"landscape": true` for a
dashboard-like report.

## The theme

Built-in themes: `editorial`, `corporate`, `minimal-light`, `minimal-dark`, `tech-dark`, `warm`, `mono`,
`bold-gradient`, and the brand kit by default. A theme is also an object of overrides on a base, which is how
the direction you chose becomes the document's: `{"base": "editorial", "accent": "#0f5257", "hero": "#10302f",
"heroAccent": "#e9c46a", "heading": "Fraunces Bold", "body": "Source Serif 4", "arHeading": "Amiri Bold",
"arBody": "IBM Plex Sans Arabic"}`.
- `hero` paints the cover, the bands and the chapter pages.
- `accent` paints the rules, numbers and links.
- `surface` paints the callouts and table bands.

A serif body (`"Source Serif 4"`, Newsreader) suits long reading; a sans body suits a manual or a CV.

## The look

The theme is the colours and faces; the `look` is how the pages are composed. It is the larger half of what makes
one PDF not look like the last: the measure and the margins, how a section opens, and what a heading, a callout,
a quote, a figure, a card and a table look like.
- `editorial`: the text at the left with a margin for notes at the right; paragraphs set like a book's, the
  first line of each indented with no space between; a section opens under a hairline with its number in small
  capitals; h2s under a rule; quotes as centred pull quotes; stats and cards under rules; callouts between
  rules; tables with no header fill.
- `swiss`: the text set in from the left, and the h2s hung in the margin beside the text they head; a section
  opens under a heavy rule, its number hung in the margin; stats and cards under bars of the accent; nothing
  filled.
- `bold`: the text the full width of the page, a little larger; each section opens on a field of the accent
  with its number large; h2s in the accent; stats on accent tiles, callouts filled, cards on the theme's dark
  colour, tables with an accent header.
- `soft`: a centred column; centred openers, the number on a pill; callouts as rounded panels with an icon;
  quotes and stats on rounded cards; cards with their icon in a tinted disc.
- `minimal`: wide margins and a centred column; small-capital h2s; outlined callouts and cards; quotes in
  italic; no running head, the page number centred.
- `classic`: the text set in beside a margin for notes; numbered openers over a short rule; callouts, stats
  and cards on the surface.

A look without a `cover` style gives its own (classic full, editorial and minimal minimal, swiss type, bold
split, soft band); with no `look`, a theme named for one gives it (editorial → editorial, tech-dark → swiss, warm →
soft, mono → minimal, bold-gradient → bold), else its `kind`, eyebrow or title decides (a proposal → bold, a report
→ editorial, a guide, a CV or an invoice → swiss, a brochure → soft, a letter → minimal), then a custom theme's base,
then its shape. That is a fallback: choose the look yourself, matching the direction and the kind (the table above),
and don't give every document the same one. Classic only when the user wants the plain look.

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
| a definition, a date, a source next to a paragraph | `aside` on the `p` |
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
- Paragraphs run 2–4 sentences. Use **bold** for the phrase a skimmer needs, not for whole sentences.
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
4. **Another format** is `export`; a new render under a new name is never how to change a document.

## Example: a short report

```json
{"document": {
  "title": "Riyadh coffee market 2026", "subtitle": "Where specialty coffee grows next", "author": "Qahwa House strategy team",
  "date": "October 2026", "organization": "Qahwa House",
  "theme": {"base": "editorial", "accent": "#0f5257", "hero": "#10302f", "heroAccent": "#e9c46a",
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
      {"note": "Sources: GASTAT household counts 2025; Qahwa House café census, September 2026."}]}]}}
```
