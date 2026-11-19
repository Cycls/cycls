---
name: style-recipes
description: Named styles for talking-head overlays, narrated explainers, logo stings, covers and motion effects, in Cycls terms (look, motif, move, piece). Load when a person names a style.
---

# style-recipes: a named style, made with a look (promos and product ads: `promo-recipes`)

Load it when the person names a style ("whiteboard", "split-flap", "pop art", "dark premium", "stop motion") or wants
a feel the twelve looks do not give by themselves. Pick ONE recipe for the video (a campaign shares one). Each
names its look, what you add on top (a motif in the scene's markup, a data-anim preset, an at() move, a `motion`
piece, a Lottie accent, a seam), what to avoid, and one check to add to the sheet review (`video-direction` §9).

Everything else stays as `video-direction`, `motion-design` and the skill for the kind of video say:
- Colours a recipe names go in ONE rule, `#root[data-look] { --look-accent: …; --look-bg: …; --look-ink: …; }`
  (`video-direction` §4); a brand kit wins over them. Never a font, a size or a colour on a role; your own text uses
  `var(--look-display)` or `var(--look-text)`.
- Frame 0 is a finished thumbnail (never dark, never the logo); what is sold is named by 2 s; the logo lands last.
  Landed words hold dead still (move the ground, the picture, the camera). Nothing that shows a value overshoots.
- A recipe's own seam (a wipe, a flood, a peel) counts as one of the one or two transitions a reel of 20 s or
  less may have; its other cuts are hard, on the beat.
- Arabic: a move that goes letter by letter goes word by word; strokes, wipes, rows and carousels run from the
  right; outlines, glows, gradient fills and letter-spacing are for Latin words only; Western digits unless the
  brand uses Arabic-Indic.
- Only what the person has: their photos, cut-outs (PNG with transparency), screens, clips and logo (SVG for anything
  drawn along its outline), stock footage, and simple shapes you draw in SVG or CSS. Facts, prices, specs and quotes
  come from them.

Times are ms unless marked s; LAND, GLIDE, MOVE, DRIFT, LEAVE, POP, SPRING, BOUNCE are `motion-design` §4; G1–G6 are
the motifs of `video-direction` §7.

## Talking-head overlays (the person's own footage; load `footage-video`)

One graphic at a time, off the face, timed from the footage reply's word times. `note` takes `text` (key words
starred, up to 4), `style`, `mark_at`, `label` and every piece's accent, background, font and duration; one note shows
at a time. A board or a table that builds is your own markup, as below.

**Highlighter notes** (for: study tips, book notes, calm talks) — editorial or warm — `motion {name, piece: "note",
start, vars: {text, style: "highlighter", mark_at}}`, the line as said; back to the face between notes; `phrase`
captions. Avoid: two marked phrases in one note, a note that paraphrases. Check: the stroke lands on the spoken word.

**Whiteboard marker** (for: concept breakdowns, lessons) — minimal on white — one idea: `note` style `marker`. A
board that builds (≤6 ideas): a card scene beside the boxed speaker (`footage-video` §4), each keyword `wipe`d on its
word, an arrow drawn (`motion-design` §7) when the speaker links two ideas, earlier ideas dimmed to .4, one accent
word a board for the "but"; the full board held 1.5–2 s. Avoid: an arrow for a link nobody said, clip art. Check:
the last board reads on a phone.

**Spec sheet** (for: gadget, software, pricing reviews) — tech or swiss — one spec: `note` style `spec` with `label`.
A table: a black panel in the split layout (lower half on 9:16, a side panel on wide), a row added as each spec is
said (the label slides 8 px; a value `count`s only when it is a quantity), the accent on the row being discussed,
earlier rows grey; a comparison is two aligned columns. Avoid: over 8 rows, a value not said or sourced. Check: each
value and unit matches its source.

**Red pen** (for: fact-checks, history, investigations) — editorial, `--look-bg: #EFE6D2` — one claim: `note` style
`red-pen`. With evidence: the person's documents slide in as if laid on a desk (rotate 2–3°, 250 ms LAND) and push
1→1.03 while read; the pen touches only the claim said (`lottie:accent-circle` with `data-color`, a strike drawn from
the start side, the correction `wipe`d beside it). Avoid: two red marks in a beat, a reconstruction not labelled as
one. Check: every correction has a source.

**Electric impact** (for: founder stories, growth recaps, hot takes) — bold, `--look-bg: #0F1C2E`, a red accent — one
number: `note` style `impact`. A run of figures: a `num` beside the face in the split panel on its word, bars a row at
a time (`motion-design` §7), only the last in the accent; then a punchline card whose key word slams (`motion-design`
§6). Avoid: two red things on a screen, glow on Arabic or body text. Check: every figure as said, not rounded further.

**Stamped keywords** (for: fitness tips, hot takes, walk-and-talk vlogs) — pop or bold — the punch line of
`footage-video` §5: one or two spoken words on its blocks beside the face, each on its syllable (Latin letters may pop
1.15→1, 40 ms apart; Arabic whole words); a contrast pair in opposite corners; off on the next beat (`steps(1,
end)`). Avoid: sentences, a word not said, bare words on bright footage. Check: clear of the eyes and mouth.

**Bold words, thin numerals** (for: creator advice, fashion talk) — editorial — in an `on-footage` scene (the look's
scrim under it): your own spans, the words in `var(--look-text)` at 800, stacked with an indent, rising a line at a
time (20 px, 220 ms); one numeral in `var(--look-display)`, larger, in the accent, fading in 600 ms after them. The
strongest line, once in 20–30 s, cuts to an `accent-bg` scene for 1–1.5 s. Avoid: two numerals at once, an invented
count. Check: the thin numeral reads on a phone.

**Wireframe inserts** (for: setup tours, gear and tech talks) — tech, `--look-bg: #10313A` — a keyword in an
`on-footage` scene (Latin `type`, Arabic `words`); when the speech names an object, a cut to an insert: the person's
photo of it or a simple SVG outline you can draw truthfully (a box, a phone, a lens) drawn in 1 s, dimension lines
250 ms later, a push 1→1.04. Avoid: a measurement not given, a keyword on every sentence. Check: each insert on its
noun, no longer than its sentence.

**Magazine pages** (for: lifestyle, outfits, personal stories, interviews) — editorial with `--look-accent: #121212;
--look-on-accent: #F2EEE6` (`card` scenes are the white pages, `accent-bg` the black) — the speaker boxed
(`footage-video` §4), one giant keyword (the hl) in the band beside the box; kicker and meta as page furniture; pages
change on a sentence with a wipe from the start side (450 ms); a Latin closing line may be an outline
(`-webkit-text-stroke: 2px`). Avoid: a word over the speaker, furniture with facts not given. Check: the face clear in
every frame.

**News explainer** (for: money explainers, current affairs, data talks) — editorial or minimal — full-frame pages
between clean speaker shots: an agenda (a body `<ul>`, the current line's `<em>` `highlight`ed), chart pages (`motion`
chart, held ≥1.5 s), `lower-third` at the first appearance. Avoid: more than two bars a comparison, colour beyond grey
and the accent. Check: each figure matches the script and its source.

## Narrated explainers (voice first; load `explainer-video`)

**Paper collage** (also: archive collage) (for: video essays, story-led ads, a life story, a company history) — riso or
warm (editorial for a life story) — 6–8 large pieces a scene: one hero (the person's cut-out, a 10 px white edge, a
soft shadow), 2–3 context pieces, the hl on a paper strip; torn edges as a fixed jagged `clip-path: polygon(…)`; each
piece drops in on its word (300 ms, POP on position, a linear fade beside); the wrapper pushes 1→1.03; one piece
carried across the cut (`motion-design` §8). Life story: navy with a ≥15% grid, dates in stamp red, numbers `count`.
Avoid: small pieces as clutter, archive-looking pictures passed off as real. Check: one clear subject a scene.

**Whiteboard doodle** (for: lessons, step-by-step processes) — minimal on white (bauhaus for schools) —
`explainer-video` §8 stations: one long `#world`, each doodle a simple SVG path drawn as its sentence names it
(0.6–1.5 s), its label `wipe`d after, the accent fill only on the object named; pan to the next patch instead of
cutting; end pulled back over the board. Avoid: detailed drawings, labels over 5 words. Check: nothing drawn before
the voice names it.

**Line drawings** (also: article illustrations) (for: everyday science, life tips, an article's ideas) — minimal,
`--look-bg: #E9E9E6`, black line art — each scene drawn stroke by stroke, a push of 2–2.5× into the detail the sentence
explains and back out (`explainer-video` §8), notes ≤4 words after their arrow. Cards: one idea a white card, a simple
round character doing it, cards sliding like a carousel (500 ms MOVE). Avoid: colour, a crowded ground, a note the
script does not say. Check: the character is the same in every scene.

**Map journey** (for: itineraries, destinations, openings across cities) — warm on a cream map — the person's map, or a
simple schematic called one on screen; the route an SVG path drawn stop to stop while the map wrapper follows its head;
at each stop a landmark or photo cut-out pops up (300 ms) with one fact, 2–4 s; end on the whole route. Avoid:
invented borders, more than 5 stops in 30 s, labels over the route. Check: every place where it really is.

**Pastel flat** (for: onboarding, brand education, how-it-works) — warm or pop, a pastel `--look-bg` — flat rounded
shapes, no outlines; each 3–5 s shot shows one visible change (windows lighting one by one at fixed offsets, a shutter
rising) while the world wrapper pushes 4–6%; `fade` seams of 0.35 s on sentence boundaries; `phrase` captions on a
dark pill. Avoid: neon, a gradient on every object. Check: one change a shot; characters keep their proportions.

**Paper diorama** (for: history lessons, craft and process stories) — warm at dusk, luxe at night — 4–6 flat paper
planes a scene (sky, hills, buildings, water, a foreground prop, each with a soft drop shadow) rising back to front 280
ms apart (LAND); `motion-design` §7 parallax; time passes in light: a night layer over the sky fades in over 2–3 s,
windows switch on at fixed offsets; a chapter title on a torn label. Avoid: photo textures in the planes, two props
moving at once. Check: no plane's edge shows during the push.

**Pixel level** (for: game and retro topics, kids' science) — pop or tech — `<rect>`s on a 160×90 grid (90×160
vertical) scaled ×12, `shape-rendering="crispEdges"`, ≤16 colours; moves stepped at 12 a second (`steps(N, end)`, N =
duration ÷ 83 ms); a dialogue box along the bottom (Latin `type`, Arabic `words`), each line held 1 s; each fact an
event in the level and a `+1` chip. Avoid: smooth tweens on sprites, real game characters. Check: the corner counter
matches the facts told.

**Course slides** (for: lessons, webinars, frameworks) — swiss or minimal, `--look-bg: #EFEBE3`, a brick accent — the
hl `type`, a rule drawn under it (500 ms), one diagram a slide built in reading order (lines, nodes, labels),
`lottie:accent-check` on the spoken word; the speaker as a round piece (`border-radius: 50%`, 280 px) in an end-side
corner inside the safe band; `fade` 0.3 s between slides. Avoid: icons, a second accent, the speaker over a diagram.
Check: each reveal on its phrase.

**Handmade stop motion** (also: clay, felt, paper cut-outs) (for: kids' lessons, cosy brand spots, seasonal greetings,
how it works) — pop (clay), warm (felt), bauhaus (paper) — clay: rounded shapes with a top-left `radial-gradient`
highlight; felt: an inner dashed stitch (`outline: 6px dashed #FFF4E2; outline-offset: -14px`); paper: a 6 px white
border, a hard `5px 7px` shadow. On twos (`steps(N, end)`, N = duration ÷ 83 ms) with a 1–2 px jitter from a fixed
list; one action a scene; a payoff shape held 1 s. Avoid: jitter on words, two hops at once, glossy plastic. Check: it
reads as stepped, and every banner is still.

**Storybook night** (for: fables, folk tales, Ramadan bedtime stories) — luxe (G2) — flat layered hills (wobbly SVG
paths, no full-frame gradient: it bands), a moon, stars joined into a shape line by line (300 ms apart), one glow
growing once; a parchment page low on the start side, one story line at a time (`rise`), a 0.3 s crossfade between
lines; a push 1→1.05. Avoid: frightening pictures for children, a myth's origin stated without a source. Check: the
page matches the voice; the hero never cut by the frame.

## Brand and covers

**Bold type poster** (for: launches, offers, one benefit) — bold or swiss — one oversized word or number at 50–70% of
the frame (G3, here meant to be read), the product cut-out overlapping it, one line, small print; the word `wipe`s or
settles 1.1→1 (500 ms LAND), the product 150 ms later; all held ≥2 s. Avoid: more than three type sizes, a discount not
given. Check: the last frame works as the still poster.

**Editorial poster** (for: product drops, issue announcements, quiet series) — editorial on warm paper (sage, stone for
the next) — hairline rules drawn first (0.8 s, from the start side), one object rising 35 px (1.1 s GLIDE), one large
hl word (Latin letters from below 80 ms apart; Arabic `rise`), kicker and meta after; in a series the next poster
wipes up as the old drifts up 60 px. Avoid: filling the empty space, moving the title. Check: ≥40% of the frame empty;
equal margins.

**Riso print** (for: gigs, pop-ups, markets, nostalgic sales) — riso — halftone dots blooming from the centre
(`clipPath: circle()` over 1.5 s, dots on frame 0), line work a layer at a time (500 ms, 100 ms apart), each hl line
stamping (320 ms) with a ghost copy in the other ink 8 px off settling into register (`aria-hidden`), details `type`d,
a stamp at ~60% with a 2-frame shake and `sfx:stamp`. Avoid: a third ink, a wobble on words. Check: dates, times and
places exactly as given.

**Documentary moment** (for: app and service promos, customer stories, founder notes) — cinematic on footage — 8–15 s
in three beats: the person and the problem, the product working (its real screen at 80% of the frame), the person
after; hard cuts, a push 1→1.1 on each `<video>`; `lower-third` once; `word` captions; the end card held 2 s. Avoid: an
invented testimonial, a customer without consent, more than one claim. Check: it reads with the sound off; captions off
the face.

**Glitch sting** (for: the closing ident of a tech, music, gaming or fashion brand) — tech (riso for music) — three
copies of the logo, two in red and cyan (`mix-blend-mode: screen`) 4–12 px off, and 3–5 slices (`clip-path: inset`)
displaced on `steps(1, end)`: two or three bursts of 2–4 frames, then at 1.4 s the logo snaps clean and holds;
`sfx:glitch-1` on a burst, `sfx:impact-bass-1` on the snap. Or the GPU `glitch` seam into a plain logo scene. Avoid:
flashes over 3 a second, a glitch longer than the hold. Check: the last frame is the supplied logo.

**Logo stings** (also: cinematic logo, liquid logo, glass icon) (for: the close of a brand film, or an ident the person
asks for) — the plain way is `logo-reveal`; when the sting is the shot: drawn in light (cinematic: an SVG logo's
outline drawn in 1.5 s, filled as it fades, one sheen, the wordmark `blur-in`); drops (pop, warm: 5–8 circles of the
brand colour converging on the mark, the exact logo crossfading in over 300 ms); an app tile (tech: the icon growing
from 80%, one sheen, sliding aside for the wordmark). Avoid: frame 0 of a promo, dust, flares, glass, rainbow rims.
Check: the supplied logo, exact and still ≥2 s.

**Cover frame** (for: a thumbnail or social cover from a talk) — frame 0 of the video — the strongest line actually
said (from the footage reply, ≤6 words, Arabic ≤5) over a real frame of the person, face large: a loud set (`accent-bg`
in yellow or red, heavy caps, a rotated tag) or a quiet one (paper or navy). Avoid: a title the video does not
deliver, small text. Check: the sheet's first cell reads at 160 px wide.

## Motion effects

**Sticker peel** (for: a playful seam in drops and list videos) — pop or warm — the next scene starts under the
outgoing one (`data-start="s1 - 2"`, the outgoing z-index higher); its `clip-path: polygon(…)` loses one corner along a
straight diagonal (the same number of points in every keyframe; a 0.5 s lift, then 1.2 s MOVE, done 0.3 s before its
end), a flap (a triangle in `linear-gradient(#F1ECE3, #BFB5A6)`, a soft shadow) mirroring the corner removed; small
stickers pop in after. Avoid: two peels at once, a flap with no shading. Check: ≥1.5 s of still reading between peels.

**Freeze** (for: the peak of a sports, dance or splash shot) — only with a still of that exact moment from the person
— the clip plays 1.5–2 s, cuts to the still on the peak with a white flash (60 ms) and `sfx:camera-shutter`; for 3–4 s
the still pushes 1→1.2 with a sideways drift and a cool edge tint fades in; a softer flash back into the clip from the
peak's media time. Avoid: more than one freeze a clip, anything moving but the camera. Check: the still matches the
frame it replaces.
