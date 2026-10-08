"""The Design tool as the model is given it: its definition — what each action takes and
how a spec is written — and the short form a chat carries until it designs
(`DESIGN_INSTRUCTIONS=on-demand`). The executor is run.py."""
import contextvars, re


# Visual design (social posts + slides), backed by the shared cycls-design
# service (see cycls/_agent/design). Enabled by "Design" in allowed_tools, but
# only offered when the service is configured — else silently absent, like an
# unconfigured office-render. The model describes a design as a spec; the service
# renders it to an image (shown on the canvas) plus an editable .fig source.
_DESIGN_TOOL = {
    "type": "custom",
    "name": "design",
    "description": (
        "Create a visual design — a social-media post or a slide — and show it to "
        "the user on the canvas. You describe the design; the service renders it to "
        "an image and to an editable design file saved in the workspace.\n\n"
        "Two ways to call:\n"
        "- render {spec, name, format?} — the normal way. `spec` is a JSON design:\n"
        "    {\"size\": [W, H] | \"<preset>\", \"fill\": <paint>, \"nodes\": [ ... ]}\n"
        "  Coordinates are pixels from the top-left. `size` takes a preset name instead of "
        "[W, H]: square 1080×1080, post-portrait 1080×1350, story / reel 1080×1920, "
        "slide / wide 1920×1080, x-post 1600×900, a4-poster 1240×1754 (print-ready at the "
        "default @2x).\n"
        "  A <paint> (any `fill`, or a text `color`) is a solid \"#4f46e5\" OR a "
        "gradient {\"gradient\":[\"#4f46e5\",\"#db2777\"], \"angle\":135} — even stops, "
        "angle 0=→ 45=↘ 90=↓ 135=↙ (or placed stops [[\"#a\",0],[\"#b\",0.6],[\"#c\",1]]). "
        "A glow is a radial gradient: {\"gradient\":[\"#fde68a\",\"#b4530900\"],\"type\":\"radial\","
        "\"center\":[0.7,0.3],\"radius\":0.6} (centre and radius are fractions of the box). "
        "A colour may carry alpha as #rrggbbaa. A gradient background reads far richer "
        "than a flat colour.\n"
        "  Node types (every node needs its `type`):\n"
        "    text    {\"type\":\"text\",\"text\":\"…\",\"x\":,\"y\":,\"w\"?:,\"size\":,"
        "\"font\"?:\"Playfair Display Bold\"|{\"family\":,\"style\":},\"weight\"?:100-900,\"italic\"?:bool,"
        "\"color\":<paint>,"
        "\"align\"?:\"left|center|right\",\"lineHeight\"?:px,\"letterSpacing\"?:px,\"opacity\"?:0-1,"
        "\"h\"?:,\"fit\"?:\"shrink\"}  (with `h`, fit:\"shrink\" steps the size down until it fits the box)\n"
        "    rect    {\"type\":\"rect\",\"x\":,\"y\":,\"w\":,\"h\":,\"radius\"?:,\"fill\":<paint>,"
        "\"stroke\"?:\"#hex\",\"strokeWeight\"?:,\"opacity\"?:,\"shadow\"?:}\n"
        "    ellipse {\"type\":\"ellipse\",\"x\":,\"y\":,\"w\":,\"h\":,\"fill\":<paint>,\"stroke\"?:,\"shadow\"?:}  (a circle when w==h; "
        "only a `stroke` and no `fill` = an outline ring)\n"
        "    line    {\"type\":\"line\",\"x\":,\"y\":,\"w\":,\"h\"?:2,\"fill\":\"#hex\"}  a thin divider\n"
        "    image   {\"type\":\"image\",\"src\":\"attachments/photo.jpg\",\"x\":,\"y\":,\"w\"?:,\"h\"?:,"
        "\"fit\"?:\"cover|contain\",\"radius\"?:,\"opacity\"?:,\"shadow\"?:}\n"
        "    stack   {\"type\":\"stack\",\"x\":,\"y\":,\"w\"?:,\"gap\"?:24,\"direction\"?:\"vertical|horizontal\","
        "\"align\"?:\"start|center|end\",\"anchor\"?:\"top|center|bottom\",\"children\":[nodes without x/y]}\n"
        "    icon    {\"type\":\"icon\",\"name\":\"lucide:rocket\",\"x\":,\"y\":,\"size\":64,\"color\"?:}  any Iconify icon "
        "(sets: lucide, tabler, mdi, ph, heroicons, ri…)\n"
        "    svg     {\"type\":\"svg\",\"src\":\"brand/logo.svg\"|\"svg\":\"<svg…>\",\"x\":,\"y\":,\"w\":,\"h\"?:,\"color\"?:}  a logo or mark\n"
        "    qr      {\"type\":\"qr\",\"text\":\"https://…\",\"x\":,\"y\":,\"size\":240}\n"
        "    line    {\"type\":\"line\",\"from\":[x,y],\"to\":[x,y],\"color\":,\"width\"?:4,\"end\"?:\"arrow\",\"start\"?:\"arrow\"}  "
        "(a connector or pointer; the old x/y/w form is a divider)\n"
        "    list    {\"type\":\"list\",\"items\":[\"…\"],\"marker\"?:\"•|1.|—|none\",\"x\":,\"y\":,\"w\":,\"size\":,\"color\"?:}  "
        "bullets or steps with a hanging indent (right-to-left for Arabic)\n"
        "    chart   {\"type\":\"chart\",\"kind\":\"column|bar|stacked|line|area|pie|donut\",\"x\":,\"y\":,\"w\":,\"h\":,"
        "\"data\":{\"labels\":[…],\"series\":[{\"name\":,\"values\":[…],\"color\"?:}]},\"values\"?:true,"
        "\"prefix\"?:\"$\",\"suffix\"?:\"%\",\"short\"?:true}  real data → a clean chart\n"
        "    table   {\"type\":\"table\",\"x\":,\"y\":,\"w\":,\"columns\":[…],\"rows\":[[…]],\"widths\"?:[fractions],"
        "\"headerFill\"?:,\"zebra\"?:}  rows sized to their text\n"
        "  A text takes \"runs\":[{\"text\":\"Grow \"},{\"text\":\"3×\",\"color\":\"#f59e0b\",\"font\":\"Playfair Display Bold\"}] "
        "instead of `text` for mixed styles in one line. Any node takes `blur`, and `backdropBlur` "
        "(frosted glass: a translucent card, e.g. fill \"#ffffff26\", over a photo). An image takes "
        "shape:\"circle\" (an avatar), `focus`:[x,y] (0–1, what stays in frame when cover crops) and "
        "`crop`:[x,y,w,h] (fractions). Photos up to 15 MB are fine — they're fitted to their box.\n"
        "  A STACK lays its children out one after another, `gap` apart, from their REAL "
        "measured sizes — a headline that wraps to three lines pushes the subtitle down. "
        "Use one for every block of text (eyebrow → headline → subtitle → button): no y to "
        "guess, nothing overlaps. In a vertical stack a text child without `w` wraps to the "
        "stack's width and takes its `align`; `anchor`:\"bottom\" makes `y` the stack's "
        "bottom edge (a caption block over a photo). A stack of text, shapes and photos stays "
        "ONE block named by its `id`: `move` or `duplicate` it by that name, and a line edited "
        "longer pushes the rest down, in the editor too. Give any node an `id` (\"headline\") "
        "— it's the node's name in the file, for edits and the layout check.\n"
        "  An image is a PNG / JPEG / WebP / GIF already IN the workspace (an upload, a stock "
        "photo you saved, brand/logo.png) — `src` is its path; save a web image to the workspace "
        "first. Or NAME a photo to find: \"stock\":\"coffee beans on wood\" in place of `src` "
        "(a deck slide's image: {\"stock\":\"…\"}) — a stock photo is found, saved to "
        "attachments/stock/ and credited in the result; `pick`:1 takes the next one. `cover` (default) fills the w×h box and crops the overflow; `contain` fits the "
        "whole image inside it (logos). Give w, h or both — a missing one follows the image's "
        "aspect. A full-bleed photo background = an image at 0,0 the frame's size FIRST in "
        "`nodes`, then a SCRIM behind where the text sits — a rect whose gradient fades from "
        "transparent to dark, e.g. fill {\"gradient\":[\"#00000000\",\"#000000cc\"],\"angle\":90} "
        "over the lower half (no hard edge across the photo) — and text with an explicit light "
        "`color` on top; the auto text colour only knows the frame's fill, not a photo. "
        "A round avatar = a square image with radius = w/2.\n"
        "  `shadow` is true or {\"blur\":40,\"y\":16,\"opacity\":0.25,\"color\"?,\"x\"?,\"spread\"?} "
        "— a drop shadow that lifts a card or button off the background.\n"
        "  DESIGN — make it look intentional, not a wireframe: one clear idea, a strong "
        "hierarchy (a big bold headline 72–120px, a small letter-spaced eyebrow ~24px "
        "with letterSpacing 4–6, a muted subtitle ~32px), a tight palette (a gradient "
        "or one background colour + white / near-white text + ONE accent), generous "
        "margins (~8–10% of the width), and a touch of depth (a shadow on the button or "
        "a card, or a big soft low-opacity ellipse bleeding off an edge for flair). "
        "A pill button = a rect with radius = h/2 and centered text.\n"
        "  FONTS: any Google Font by its exact family name plus a style — \"Playfair Display "
        "Bold\", \"DM Sans Medium\", \"Montserrat Extra Bold Italic\", \"Bebas Neue\" — or "
        "{\"family\":\"Poppins\",\"style\":\"Semi Bold\"}; `weight` and `italic` work too; the "
        "default is Inter. Pair a characterful headline face (a serif or display font) with a "
        "clean sans for body copy. Arabic text needs an Arabic font — Cairo, Tajawal, Almarai, "
        "IBM Plex Sans Arabic, Amiri, Noto Kufi Arabic, Readex Pro; any other face falls back "
        "to Noto Naskh Arabic. Arial / Helvetica / Times are swapped for their open twins. A "
        "font that doesn't exist is an error; a weight the family lacks falls back to Regular "
        "— the result tells you either way.\n"
        "  BRAND: if the workspace has a brand kit (brand/brand.yaml), what you leave out comes "
        "from it: a background `fill` → the brand primary, a shape `fill` → the accent, a text "
        "`font` → the brand heading face (display sizes, ≥48px) or body face — or write the "
        "brand's colours and fonts yourself. Text with no `color` gets white or near-black, "
        "whichever reads on its background.\n"
        "  LAYOUT: put text blocks in a stack. Text outside one needs room to WRAP — "
        "give any multi-word text a `w` and put the next node below the whole wrapped "
        "block. Every render comes back with a LAYOUT CHECK (overlapping text, text off or "
        "crowding an edge, text too small, low contrast on what's behind it) — fix what "
        "it lists before you present.\n"
        "  RTL: for Arabic / Hebrew set text `align`:\"right\" and give it a `w`, then "
        "ANCHOR it to the right margin — place the box so its right edge (`x`+`w`) sits "
        "inside the frame (`x` ≈ frameW − margin − `w`), NOT at the small `x` you'd use "
        "for left-aligned English (that runs the text off the right edge). Shaping, bidi "
        "(mixed digits / Latin) and diacritics are automatic, so write the text naturally "
        "— but skip `letterSpacing` on Arabic.\n"
        "- A presentation DECK: pass a deck of LAYOUTS — the normal way. You fill each slide's "
        "slots; the service lays them out, so every slide shares margins, title position, type "
        "scale, footer and page numbers, and nothing is placed by hand:\n"
        "    {\"deck\": {\"theme\": \"editorial\", \"footer\"?: {\"text\": \"Brewly · Seed 2026\"}, \"slides\": [\n"
        "      {\"layout\": \"title\", \"eyebrow\"?:, \"title\":, \"subtitle\"?:, \"meta\"?:, \"image\"?: \"attachments/hero.jpg\", \"notes\": \"…\"},\n"
        "      {\"layout\": \"bullets\", \"title\":, \"bullets\": [\"…\"], \"image\"?:, \"notes\": \"…\"}, … ]}}\n"
        "  Layouts and slots: title {eyebrow?, title, subtitle?, meta?, image? (full-bleed), align?:\"center\"} · "
        "section {number?, title, subtitle?} · agenda {title, items} · bullets {eyebrow?, title, subtitle?, "
        "bullets, image?} · two-column {title, left:{heading?, text|bullets}, right:{…}} · image-left / "
        "image-right {eyebrow?, title, text|bullets, image} · image {image, title?, caption?} (full-bleed "
        "photo) · quote {quote, author?, role?, image?} · stats {eyebrow?, title?, items:[{value, label}] "
        "(1–4)} · timeline {title, items:[{date, title, text?}] (2–6)} · table {title, columns, rows, "
        "caption?} · chart {title, chart:{kind, data, …chart keys}, caption?, takeaway?:{value?, text}} · "
        "team {title, people:[{name, role?, photo?}] (≤8)} · closing {title, subtitle?, cta?, contact?, "
        "qr?:\"https://…\"} · poll {question, options (2–6)} (a LIVE poll: when the deck is "
        "presented the audience votes from their phones — the presenter shows a join QR — and the bars "
        "fill live; exports show the empty poll) · custom {nodes, fill?} (a hand-built slide, for what no "
        "layout fits). Every "
        "slide also takes notes, transition, id. Images are workspace paths.\n"
        "  Themes: minimal-light, minimal-dark, bold-gradient, editorial, corporate, tech-dark, warm, mono, "
        "\"brand\" (the workspace brand kit — the default when one exists), or overrides on a base: "
        "{\"base\":\"minimal-dark\",\"accent\":\"#f59e0b\",\"heading\":\"Sora Bold\"}. An Arabic slide is laid out "
        "right-to-left and an English one left-to-right, automatically; a slide mixing both (an Arabic "
        "headline over English bullets) follows the deck's `dir` — set \"dir\":\"rtl\" on an "
        "Arabic-first bilingual deck (else the language with more words decides). Keep slide text short — titles shrink to fit their place, "
        "and the layout check names anything that still doesn't fit.\n"
        "- A deck of hand-built frames (or a carousel), when you need full control:\n"
        "    {\"frames\": [ {\"size\":\"slide\", \"fill\":…, \"nodes\":[…], \"id\"?:\"cover\", "
        "\"title\"?:\"Cover\", \"notes\"?:\"what the presenter says\", \"transition\"?:\"fade|slide|none\"}, … ]}\n"
        "  one object per slide, every slide the SAME size. format \"pptx\" is one PowerPoint "
        "file — each slide's speaker `notes` and `transition` are written into it, and its text, "
        "rects, ellipses and lines stay editable there, charts and tables are PowerPoint's own "
        "(their data edits there), Arabic keeps its side (gradients, icons, SVG, photos and "
        "blurs become pictures, one element each; decor bleeding off a slide "
        "is cropped by the slide in the show). \"pdf\" is one page per slide, its words searchable. png / jpg / webp "
        "save every slide as its own image, <name>-slide-1, -slide-2 … (an Instagram carousel). "
        "Write notes for a talk deck. Every slide comes back to you to QA.\n"
        "  PAGES — one design, several VARIANTS of the same piece of work (a post, a story and a "
        "banner of one campaign; a light and a dark version): spec = {\"pages\":[{\"name\":\"Post\","
        "\"size\":\"square\",\"fill\":…,\"nodes\":[…]}, {\"name\":\"Story\",\"size\":\"story\",…}]} — each page "
        "a design of its own (its own size; or {\"name\", \"frames\":[…]} for a carousel), under a "
        "name no other page has. It is ONE file (designs/<name>.fig) whose pages the user switches "
        "between in the editor, previews and downloads one at a time; each page's image is saved "
        "too (<name>.png the first, then <name>-page-2.png, -page-3 …). Use pages when the user "
        "asks for the same thing in several formats or versions — not separate renders, and not "
        "for a deck's slides (those are `frames` / a `deck`). Lay each page out for ITS size: "
        "never the same coordinates on another shape.\n"
        "  A DOCUMENT — a report, a proposal, a white paper, a guide, a brochure, a CV: anything that "
        "is read on paper-sized pages and comes out as a PDF — is spec = {\"document\": {\"title\", "
        "\"subtitle\"?, \"author\"?, \"date\"?, \"organization\"?, \"size\"?: \"a4\"|\"letter\"|\"a5\" "
        "(\"landscape\": true), \"theme\"?, \"cover\"?: {\"style\": \"full\"|\"band\"|\"minimal\"|\"split\"|\"type\", "
        "\"eyebrow\"?, \"image\"?}, \"openers\"?: \"plain\"|\"band\"|\"page\", \"columns\"?: 1|2|3, "
        "\"sections\": [{\"title\", \"summary\"?, \"blocks\": […]}], \"back\"?: {\"title\", "
        "\"text\", \"contact\"}}}. You write the CONTENT, in order; the pages make themselves: text flows "
        "from page to page, a heading never ends a page, the contents page, running header and page "
        "numbers are added. A block is {\"<kind>\": …}: \"lead\" (the opening paragraph) · \"p\" (or a "
        "bare string; takes **bold**, *italic*, [links](https://…)) · \"h2\" · \"h3\" · \"bullets\" / "
        "\"numbered\": [..] · \"callout\": {title?, text, tone?} · \"quote\" + \"by\" · \"stats\": "
        "[{value, label}] · \"chart\": {kind, data} + \"title\", \"caption\" · \"table\": {columns, rows} + \"title\" "
        "/ \"caption\" · \"image\": \"path\" (or {\"stock\": \"query\"}) + \"caption\" — a photo is cropped "
        "to a band, a diagram or screenshot shown whole (\"fit\": \"cover\"|\"contain\" to say) · "
        "\"columns\": [[blocks],[blocks]] · "
        "\"cards\": [{icon?, title, text}] · \"pairs\": [[label, value]] · \"note\" (a source) · "
        "\"nodes\": [spec nodes] + \"h\" (a hand-built area) · \"break\". A `p` takes \"aside\": a short "
        "note in the margin beside it — and an h2 / h3 takes it at the far end of its line (a role's dates: "
        "{\"h3\": \"Lead designer — Brewly\", \"aside\": \"2021 – now\"}); a key a block doesn't read is said "
        "in the reply, not kept; `[^key]` in any text cites the document's \"footnotes\": {key: text} "
        "(numbered, set at the end of the section); \"numbering\": true numbers figures and tables, and \"figures\": true lists them with "
        "their pages after the contents (a long report with many of them); a chart "
        "or table can read a workspace spreadsheet instead of carrying its data — \"chart\": {kind, "
        "\"from\": \"data/sales.csv\", x?, y?: [columns]} · \"table\": {\"from\": \"data/sales.csv\", columns?, "
        "limit?} (.csv, .tsv, .xlsx). A section opens a new page, or runs on under a few lines left over "
        "(\"break\": \"page\" forces one, \"none\" never). Write it as a real document: "
        "open each section with what it found, real numbers, a caption on every chart and table, short "
        "paragraphs. The LOOK is yours to choose unless the user says: the workspace brand kit when "
        "there is one (the default), else a theme that fits the subject — and its accent or fonts "
        "overridden ({base, accent, heading, body}) when that fits better. The cover sets the tone: "
        "\"full\" (the theme's dark colour — or a photo, \"image\" — the title at the foot), \"split\" (the "
        "title on a dark panel beside a full-height photo), \"type\" (the whole page in the accent, the "
        "title large: no photo needed), \"band\", \"minimal\" (quiet: a letterhead, a legal paper); and "
        "\"openers\": \"band\" opens each section on a band of the dark colour — for a report meant to "
        "look designed, where \"plain\" is the sober choice — and \"openers\": \"page\" gives each section "
        "a chapter page of its own (its number, its title, and its \"summary\": one line of what it holds): "
        "for a long report or a book-like document, not a short one. \"columns\": 2 sets the text in two "
        "columns — a newsletter, a magazine piece, a paper (3 for a dense bulletin or a reference sheet); what is "
        "wide (a section's opening, its lead, charts, tables, stats) spans them, and the columns are evened out by "
        "themselves. The PDF carries the document's title, `author` (else `organization`) and subtitle as its own; "
        "give \"lang\" (\"en\", \"fr\", …) for its language — Arabic is known without. It saves designs/<name>.pdf "
        "and opens in the page viewer; every page comes back to you to QA (past twelve pages: the first "
        "four to read, the rest small on contact sheets — look at how each is laid out). A small fix on one page is "
        "an `edit` (ops with `frame`: the page, from 0). Anything that changes the length is made on the "
        "document itself, and only the part that changes is sent: update_section {name, number, section: "
        "{title?, blocks?}} · add_section {name, section, at?} · move_section {name, number, to} · "
        "delete_section {name, number} · update_document {name, document: {title?, theme?, cover?, …}} — "
        "`inspect` lists its sections; it is rendered again in place (the earlier version is kept). Or "
        "the whole render again with \"replace\": true. Never a new name for a change. If the user edited "
        "its pages by hand since the last render, the tool says what they changed instead of rendering: keep "
        "their wording in what you send, tell them what can't be kept, then repeat with \"discard_edits\": true. "
        "A one-page CV, a letter, an invoice, a brief has no cover page: \"cover\": false — its title heads "
        "page 1 (\"kind\": a small label over it; \"meta\": a line under it, e.g. contact details), sections "
        "run on under compact headings, and a few lines too many for the page are set a little tighter to fit. "
        "When it must fit a number of pages — a one-page CV — say \"max_pages\": 1: its type is set smaller, "
        "down to 85%, until it does, and the reply says if even that isn't enough (then cut content, once).\n"
        "- extract {path, name?} — an EXISTING PDF taken apart to be redesigned: its text page by page "
        "(in reading order, its tables as they are laid out; a long one a few pages at a time — the reply "
        "says how to read on: \"pages\": \"5-12\"), and its pictures saved into "
        "designs/<name>-assets/ to use again; then write it as a document. A chart or diagram drawn in "
        "the PDF is not among its pictures: extract {path, page: N} shows that page, and with "
        "\"area\": [left, top, width, height] (parts of the page, 0 to 1) cuts the figure out and saves it. "
        "A scan, or text the reply says can't be trusted, is read from its pages the same way.\n"
        "- script {script, name, format?} — escape hatch: a raw OpenPencil / Figma "
        "plugin-API script for what the spec can't express. It MUST end with "
        "`console.log('__FRAME__'+frame.id)` naming the frame to export.\n"
        "- Change a DECK's slides (name = the deck): add_slide {name, slide, at?} · update_slide {name, "
        "number, slide} (rebuild it — take its layout `source` from inspect and change what you need) or "
        "{name, number, notes?|title?|transition?} · move_slide {name, number, to} · duplicate_slide "
        "{name, number} · delete_slide {name, number}. Slides are numbered from 1; a new slide takes the "
        "deck's theme and footer, and page numbers follow any change. Use these — not a re-render — to "
        "change a deck's structure; `edit` ops still tweak nodes on a slide.\n"
        "- inspect {name, page?} — the design's frames and every node by name (its `id`, else "
        "text-1, rect-2…), with its box, text, font and colour. Do this before an edit you "
        "can't name from the spec you wrote. A design with several pages lists them, and shows "
        "ONE: `page` (its name), the first when you give none. A message that carries "
        "\"[Selected in designs/<name>.fig › <frame>: <node> (<type>), …]\" is the person "
        "pointing: \"this\" / \"the selection\" means those nodes — edit them by those names "
        "(\"[… page \"Story\" › …]\" says which page they are on: pass it as `page`).\n"
        "- export {name, format, page?} — a design you ALREADY have, as another file: pdf, pptx, png, jpg, "
        "webp or svg, made from its saved .fig as it is now — with everything changed since, by you or by "
        "hand in the editor. When the user wants the same design in another format (\"send me this as a "
        "PDF\", \"I need the slides as images\"), use this, NOT render: a render makes a second design from "
        "the spec, without those changes. A deck as png / jpg is an image a slide; `page` exports one page.\n"
        "- A design as a file (name = the design): rename {name, new_name} · duplicate {name, new_name?} — a "
        "copy to change freely (a variant in another language, a second direction) · delete {name} — to the "
        "trash, where the user can restore it · versions {name} — its earlier versions (every edit and save "
        "keeps one) · restore {name, version} — go back to one (what it is now is kept as a version). What is "
        "kept beside a design — its images, slides, deck — goes with it.\n"
        "- edit {ops, name, page?, intent?} — change a design you rendered (designs/<name>.fig) with "
        "named operations, applied in order: "
        "[{\"op\":\"set_text\",\"node\":\"headline\",\"text\":\"New\"}, "
        "{\"op\":\"style\",\"node\":\"headline\",\"color\":\"#f5a623\",\"font\":\"Playfair Display Bold\"}, "
        "{\"op\":\"move\",\"node\":\"cta\",\"dy\":40}, {\"op\":\"add\",\"node\":{…a spec node…}}] — "
        "the full list is in the `ops` field. Ops paint, set fonts and lay out exactly as a "
        "render does. A node is named as `inspect` lists it — an icon, an SVG, a QR code, a "
        "list, a table and a chart are each ONE part (icon-1, qr-1, chart-1): moved, copied, "
        "removed and recoloured whole; an icon or QR is resized with `resize`. The edit is "
        "applied to the saved design first: names that don't exist are ONE error naming all "
        "of them and listing the parts that do, and nothing changes; on success the "
        ".fig is saved, its image re-exported, and the edited design comes back to you to "
        "check, with a layout check. If the design is open, the user WATCHES a labeled "
        "'Super' cursor replay the change live — pass a short `intent` ('making the "
        "headline gold') shown on it. Use `edit` to tweak a design ('bigger headline', "
        "'move the button down'); `render` to CREATE one. A chart's or table's DATA (values, "
        "labels, rows) changes by rebuilding it — update_slide with the new data, or a new render "
        "— never by moving its bars one by one (that chart then goes into PowerPoint as shapes). "
        "`name` is the design's base name "
        "(e.g. `launch`). An edit is made on ONE page — `page`, the first when absent; the same "
        "node name on another page is another node. Page ops (in `ops`) change the pages "
        "themselves: page_add {name, spec} (a new variant, `spec` as in render), page_duplicate "
        "{page?, name?} (a copy to restyle — the ops after it in the same edit land on the copy), "
        "page_rename {page?, name}, page_delete {page?}.\n"
        "  For what ops can't do, `edit` also takes a raw `script` instead: a Figma "
        "plugin-API snippet mutating the document (figma.currentPage.findOne(…)); set "
        "`figma.currentPage.selection` to what you change. Fonts there are "
        "{family:'Poppins',style:'Semi Bold'} (spaced style names); `textAlignHorizontal` "
        "follows the text's direction (on Arabic 'LEFT' is the right side).\n\n"
        "`format` is png (default), jpg, webp, svg, pptx (PowerPoint) or pdf — pptx or pdf "
        "for a deck. `name` is the file base name, e.g. `launch`. The render opens on the "
        "canvas; the editable `.fig` is saved beside it for later edits. Every render "
        "also comes back to YOU as an image (a deck: every slide) — look at it and "
        "fix what's off before you present it. A fresh "
        "`render`/`script` NEVER overwrites an earlier design — if the name is taken "
        "it gets a numeric suffix (`launch-2`); to CHANGE an existing design use `edit`."
    ),
    "input_schema": {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["render", "script", "edit", "inspect", "add_slide", "update_slide", "move_slide", "duplicate_slide", "delete_slide",
                                              "add_section", "update_section", "move_section", "delete_section", "update_document", "extract",
                                              "export", "rename", "duplicate", "delete", "versions", "restore"],
                   "description": "`render` a JSON spec (normal), run a raw `script` (escape hatch), `inspect` a rendered design (its frames and named nodes; a document's sections), `edit` it (checked, saved, replayed live in the editor), change a deck's slides: add_slide / update_slide / move_slide / duplicate_slide / delete_slide, change a document: add_section / update_section / move_section / delete_section / update_document, `extract` an existing PDF's text and pictures, `export` a saved design as another file, or handle a design as a file: rename / duplicate / delete / versions / restore."},
        "new_name": {"type": "string", "description": "For `rename`: the design's new name. For `duplicate`: the copy's name (default <name>-copy)."},
        "version": {"type": ["string", "integer"], "description": "For `restore`: the version to go back to — its id from `versions`, or its place there (1 = the newest)."},
        "section": {"type": "object", "description": "For add_section / update_section: the section {title, blocks: […]}. update_section takes just the keys that change — {blocks} rewrites it, {title} renames it."},
        "document": {"type": "object", "description": "For update_document: the document's own keys that change — title, subtitle, author, date, theme, cover, size, footnotes, numbering… (null removes one). Not its sections."},
        "path": {"type": "string", "description": "For `extract`: the PDF in the workspace, e.g. attachments/report.pdf."},
        "page": {"type": ["string", "integer"], "description": "For `inspect` / `edit` on a design with several pages: the page's name (default: the first page). For `extract`: the PDF's page to look at, a number from 1."},
        "area": {"type": "array", "items": {"type": "number"}, "description": "For `extract` with `page`: the part of that page to cut out and save as a picture — [left, top, width, height], each a part of the page from 0 to 1."},
        "pages": {"type": ["string", "integer"], "description": "For `extract`: read on in a long PDF — the pages whose text to show, e.g. \"5-12\" (the reply says which are left)."},
        "replace": {"type": "boolean", "description": "For `render` of a document: re-render it under the SAME name (after changing its content) instead of making a new one; the earlier version is kept in its history."},
        "discard_edits": {"type": "boolean", "description": "For a document's re-render (`replace`, or a section action) after the tool said its pages were edited by hand since the last render: true once those edits are accounted for — their wording put into what you send, the user told what can't be kept."},
        "slide": {"type": "object", "description": "For add_slide / update_slide: the slide — a layout slide {layout, …slots, notes?} laid out with the deck's own theme and footer, or a hand-built one {nodes, fill?}. update_slide replaces the slide whole: start from its `source` in inspect and change what you need."},
        "number": {"type": "integer", "description": "For update_slide / move_slide / duplicate_slide / delete_slide: the slide's number, from 1. For update_section / move_section / delete_section: the section's."},
        "to": {"type": "integer", "description": "For move_slide / move_section: the position it moves to, from 1."},
        "at": {"type": "integer", "description": "For add_slide / add_section: the position of the new one, from 1 (default: the end)."},
        "notes": {"type": "string", "description": "For update_slide without `slide`: the slide's new speaker notes (also `title`, `transition`)."},
        "title": {"type": "string", "description": "For update_slide without `slide`: the slide's title (its name in the deck viewer)."},
        "transition": {"type": "string", "enum": ["fade", "slide", "none"], "description": "For update_slide without `slide`: how the slide enters when presented."},
        "ops": {"type": "array", "items": {"type": "object"},
                "description": "For `edit`: operations by node name (see `inspect`), applied in order — set_text {node,text}; style {node, color?, fill?, font?, size?, weight?, italic?, opacity?, radius?, align?, letterSpacing?, lineHeight?, stroke?, strokeWeight?}; move {node, x?, y?, dx?, dy?} (a stack's id moves the whole block; a node in a stack moved on its own leaves it); resize {node, w?, h?}; delete {node}; duplicate {node, dx?, dy?, id?} (in a stack, the copy is its next item); replace_image {node, src}; add {node:<spec node>, frame?}; background {fill, frame?} — the slide's OWN fill: a colour, {\"gradient\": [...]} or \"none\" (never cover a slide with a full-size rect). `frame` (slide index from 0) narrows a name to one slide. Pages: page_add {name, spec}; page_duplicate {page?, name?}; page_rename {page?, name}; page_delete {page?}."},
        "spec": {"type": "object", "description": "For `render`: a single design {size, fill, nodes}; several variants of one design as pages {pages:[{name, size, fill, nodes}]}; a document (a report or any PDF that flows over pages) {document:{title, sections:[{title, blocks:[…]}]}}; a presentation as a deck of layouts {deck:{theme, footer?, slides:[{layout, …slots, notes}]}} (the normal way for decks); or hand-built frames {frames:[...]} (one per slide, all one size, each with optional id/title/notes/transition; export pptx or pdf, or png for a carousel); size is [W,H] or a preset (square, post-portrait, story, reel, slide, wide, x-post, a4-poster). Nodes are text/rect/ellipse/line/image/stack (image `src` = a workspace file; a stack lays out `children` from their measured sizes); a fill or text color is a solid \"#hex\" or a gradient {gradient:[...],angle}; nodes take opacity, shadow, and shapes take stroke/strokeWeight."},
        "script": {"type": "string",
                   "description": "For `script`: a Figma plugin-API script ending in console.log('__FRAME__'+id). For `edit`: a snippet mutating the open doc that also sets figma.currentPage.selection to the changed node(s). Scripts may use only `figma` (and `console`): no `this`, globals, network, eval/Function or `.constructor` — anything else is refused before it runs."},
        "intent": {"type": "string",
                   "description": "For `edit`: a short label of the change (e.g. 'making the headline gold') shown on the live 'Super' cursor."},
        "name": {"type": "string", "description": "Output file base name, e.g. `launch` (lowercase, no extension)."},
        "format": {"type": "string", "enum": ["png", "jpg", "webp", "svg", "pptx", "pdf"],
                   "description": "Output format (default png). A deck: pptx (PowerPoint, with speaker notes) or pdf; png for a carousel (one image per slide)."},
        "scale": {"type": "integer", "description": "Raster scale for png/jpg/webp (default 2 = @2x)."},
    }, "required": ["action"]}
}

# ---- Design's instructions, only when a chat designs --------------------------------
#
# The definition above is 29,000 characters: nearly half of every request of every
# chat, whether it ever designs or not. With DESIGN_INSTRUCTIONS=on-demand a chat
# carries the SHORT form below until it designs — which the person's words say, or a
# design they point at, or the model asking for the guide (`design_wanted`). From then
# on it is the definition above, byte for byte: a chat that designs is told exactly
# what it is told today. The harness swaps them (harness/main.py); what the model was
# shown when it made a call is DESIGN_LOADED, which `_exec_design` reads.

DESIGN_LOADED = contextvars.ContextVar("design_loaded", default=True)

_DESIGN_SHORT = (
    "Design: make and change visual work, shown to the user on the canvas — a social post, a poster, a "
    "banner, a carousel; a slide deck (PowerPoint / PDF); a document that flows over pages (a report, a "
    "proposal, a CV, a newsletter — as a PDF); several variants of one design; and edits to any design "
    "already in designs/ (text, colours, layout, slides, sections). It can also take an existing PDF apart "
    "to redesign it.\n\n"
    "This is the SHORT form of the tool — how a design is written is not in it. Before your first use of it "
    "in a chat, call it with {\"action\": \"guide\"}: its full instructions load into this description. Then "
    "make the call you meant. (A call made before that is not run — it loads the instructions and asks you "
    "to call again.)"
)
_GUIDE_LOADED = ("Design's instructions are loaded: this tool's description now holds them in full — how a "
                 "design is written, deck layouts and themes, documents, edits and the rest. Read them, then "
                 "call `design` again with what you want made. Nothing was made or changed by this call.")
_GUIDE_NOT_RUN = "Not run — this call was made before the tool's instructions were loaded. " + _GUIDE_LOADED

# What a person says when they want something designed (English and Arabic). Wide on
# purpose: a chat that matches and never designs pays what every chat paid before; one
# that designs without matching pays one extra call (the guide).
_DESIGN_WORDS = re.compile(
    r"\b(design\w*|redesign\w*|poster|flyer|banner|infographic|brochure|logo|mock-?up|thumbnail|carousel|"
    r"slides?|deck|presentation|pitch|powerpoint|pptx|keynote|pdf|report|proposal|white ?paper|one[- ]pager|"
    r"newsletter|cv|resume|résumé|certificate|invitation|business card|social (?:media )?post|instagram|linkedin post)\b",
    re.I)
_DESIGN_WORDS_AR = ("تصميم", "صمم", "صمّم", "بوستر", "ملصق", "بانر", "إنفوجرافيك", "انفوجرافيك", "بروشور", "كتيب", "شعار",
                    "عرض تقديمي", "شرائح", "شريحة", "عرضا", "عرض ", "تقرير", "مقترح", "سيرة ذاتية", "السيرة الذاتية",
                    "شهادة", "دعوة", "منشور", "كاروسيل", "بي دي اف", "بوربوينت", "باوربوينت")


def design_called(messages):
    """Has this chat called the Design tool — the guide included?"""
    for m in messages:
        if m.get("role") != "assistant" or not isinstance(m.get("content"), list):
            continue
        if any(isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "design" for b in m["content"]):
            return True
    return False


def design_wanted(messages):
    """Does this chat design? It has called the tool; or the person names a design file
    or has part of one selected (`designs/…`); or their words ask for one. Read back from
    the transcript each turn — as connectors are — so nothing is stored."""
    if design_called(messages):
        return True
    for m in messages:
        if m.get("role") != "user":
            continue
        content = m.get("content")
        texts = [content] if isinstance(content, str) else [
            b.get("text") or "" for b in content or [] if isinstance(b, dict) and b.get("type") == "text"]
        for text in texts:
            if "designs/" in text or _DESIGN_WORDS.search(text) or any(w in text for w in _DESIGN_WORDS_AR):
                return True
    return False


def _design_short():
    """The short form: the same tool by name, every parameter still there by name and
    type (nothing the model may pass is unknown to the schema), and none of the how."""
    props = {}
    for key, schema in _DESIGN_TOOL["input_schema"]["properties"].items():
        props[key] = {k: schema[k] for k in ("type", "enum", "items") if k in schema}
    props["action"]["description"] = (
        "guide — load this tool's full instructions (first). Then: render, edit, inspect, extract, script, "
        "add_slide, update_slide, move_slide, duplicate_slide, delete_slide, add_section, update_section, "
        "move_section, delete_section, update_document, export, rename, duplicate, delete, versions, restore.")
    return {**{k: v for k, v in _DESIGN_TOOL.items() if k not in ("description", "input_schema")},
            "description": _DESIGN_SHORT,
            "input_schema": {"type": "object", "properties": props, "required": ["action"]}}


_DESIGN_TOOL_SHORT = _design_short()


def design_tool(loaded=True):
    """The Design tool as a chat carries it: whole, or — until it designs — short."""
    return _DESIGN_TOOL if loaded else _DESIGN_TOOL_SHORT
