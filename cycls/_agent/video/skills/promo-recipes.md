---
name: promo-recipes
description: Named styles for product promos and product ads (cards, type, shapes, product shots) in Cycls terms (look, motif, move, piece). Load when a person names a promo style.
---

# promo-recipes: a named promo style, made with a look (overlays, explainers, stings: `style-recipes`)

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

## Product promos (load `promo-reel`)

**Website launch** (for: a 15–30 s launch from the product's site) — one style for the film: kinetic type (bold or
swiss), Card flight or Blueprint (below) — the site's real logo, colours, copy and screenshots; at most three
benefits, each shown working; `end-card` with the real address as `link`. Avoid: two styles in one film, a feature or
number not on the site. Check: the address and the call to action are right.

**Echo stack** (for: teasers with one strong word a beat) — bold; navy for tension, paper for the resolve — one word
in 4–7 rows filling the height, full ink and 30% ink alternating, stamping top to bottom 60–90 ms apart (scale
1.06→1); echo rows trail the hero row by 70–200 ms with a small x offset, `data-layout-ignore aria-hidden="true"`; on
the next beat the stack collapses to one row (250 ms) and the next word bursts out. Avoid: sentences, echoes on the
logo card, a cropped hero row. Check: each word reads on its first held frame.

**Split and slot** (for: a fixed phrase whose last word swaps: "Back up your photos / notes / code") — tech, a mint
accent — the swap is `motion-design` §6's slot machine; a break is the word as 3–5 copies clipped to horizontal bands
(`clip-path: inset(…)`) shooting apart sideways (350 ms LEAVE) and locking back as the next word. Avoid: overshoot,
swap words of very different length. Check: each landed word held ≥1 s, on the baseline.

**Split-flap** (for: three or four short statements, one hero number) — swiss or bold on cool paper — each line as two
copies: the top half (`clip-path: inset(0 0 50% 0)`) folds `rotateX(0)`→`rotateX(-90deg)` in 180 ms on
`transform-origin: 50% 100%`, then the new bottom half from `rotateX(90deg)`, the parent `perspective: 1200px`; lines
80 ms apart; a number rolls slot digits to its value and holds 1 s; the accent block slides in behind its word after.
Avoid: bounce, heavy 3D shadows, invented stats. Check: every line fills the width, no letter cropped.

**Card flight** (for: SaaS and app launches where the UI is the proof) — tech or brutalist — the real screenshots on
rounded cards in a parent with `perspective: 1600px`, flying in along one diagonal from `rotateX(55deg) rotateZ(-40deg)`
(Arabic `40deg`), 800 ms LAND, 120 ms apart; the hero card turns flat, grows to 70–80% of the frame and holds; a swap
flies it out the same diagonal. Avoid: spins, a metric invented inside a screen. Check: the hero screen flat and
legible ≥1 s.

**Carousel** (for: 4–8 features, plans or use cases) — pop or brutalist on near-black — portrait cards in ≤4 colours,
2–4 words and one object each (a product photo, a Lottie emoji); the row is `motion-design` §7's pan through stations,
one card a beat, then a hold, the centre card at 1.08, its words `words`; Arabic runs it the other way; the centre
card grows into the end card. Avoid: a row that never stops, paragraphs on cards. Check: the centre card whole and
readable while it holds.

**Blueprint** (for: dev tools, APIs, infrastructure) — tech, `--look-bg: #13202E`, a cyan accent — a 40 px grid at
≥15% white; the product's structure in 2 px chalk lines drawn construction first, nodes popping where lines meet (120
ms), one path at a time turning the accent; captions `type` beside their shape; the drawing drifts ≤20 px a second.
Avoid: filled shapes, every UI detail drawn. Check: it is the product's real structure.

**Two-ink dither** (for: dev tools, infrastructure, changelog teasers) — minimal or swiss, `--look-bg: #F5F1E8;
--look-ink: #0F1830`, the accent only on the logo — dot fields as a `radial-gradient` pattern whose dot radius grows to
the cell (a registered `@property --r` of syntax `<length>`, 600–900 ms); between scenes 120 px blocks switching on
`steps(1, end)` at 25 ms × (row + column). Avoid: text over moving dots, a third ink. Check: every headline sits on a
solid card, still.

**Neon type** (for: gaming gear, audio, nightlife, performance claims) — tech or pop with G5 — Latin words as a sign: an
outline copy (`-webkit-text-stroke`) revealed by a wipe, or G5's tube path drawn, then the fill switched on with G5's
flicker; 1–3 words a beat, every 1.5–2 s; a thin accent rule hands off to the logo. Avoid: glow on Arabic or body
copy, flicker loops, frames round the words. Check: each beat fully lit and readable ≥1 s.

**Shape masks** (also: ring mask, liquid blob, bubble field) (for: modular and design-led products, calm consumer
apps) — bauhaus (geometric), pop or warm (soft) — words sit inside shapes, clipped by them; a circle opens from a point
(`clipPath: circle(0%)`→`circle(75%)`, 600 ms LAND) on its word; three circles slide together into three bars
(`motion-design` §7 shape morph); a shape widening past the frame is the cut. Soft: a blob of one colour splits into
droplets and merges back, or frame 0 is a field of circles (G6) clearing outward for the headline; the last shape
floods the frame for the brand word. Avoid: text across a moving edge, gradients. Check: each word whole inside its
shape while it holds.

**Velocity** (for: fitness, sport, delivery, anything sold on speed) — bold or tech, electric blue on navy — one word a
beat sliding in from the end side (200 ms LAND; the render's blur streaks it); thin streaks (2–6 × 120–600 px, fading
at the tail) rushing the other way behind each change for 300 ms; one ring burst (scale .2→1.6, opacity 1→0) on the
main claim; a calm end card. Avoid: streaks across the read word, pulsing rings. Check: each word still ≥1 s.

**Flat story** (for: AI tools and apps told as before → click → result) — warm in two tones (`--look-bg: #F07F3C;
--look-ink: #22140C`, cream highlights) — flat SVG shapes with 3–4 px ink outlines: a person at a desk, a hand or icon
close-up landing with a squash .9→1.05→1 (300 ms), the screen's words `type`d; the reveal is a burst of cream rays
(`conic-gradient`, 400 ms) shrinking into a spiky badge (`clip-path: polygon`) behind the product mark. Avoid:
detailed faces, more than 5 words on a screen. Check: before, action and result read with the sound off.

**Ribbon flow** (for: payments, banking, logistics: three real steps) — minimal on paper grey or a deep green — one
wide SVG ribbon (a 120 px stroke, a `linearGradient` across it) drawn along its path in 1 s, then drifting under the
words; copy `words`; 2–3 round line icons popping 150 ms apart, the last becoming `lottie:accent-check`; `highlight`
on the tagline's key word. Avoid: a second ribbon, steps the product does not do. Check: the ribbon unbroken; no read
line crossed by it.

**Stickers** (for: creator and social apps, upbeat consumer launches) — pop — die-cut stickers: an 8 px white border, a
3 px navy line (`box-shadow: 0 0 0 3px #121A3A`), a hard navy offset shadow; each pops 0→1 on SPRING with ±6° (a linear
fade beside), 150 ms apart; the logo ends as one big sticker. Avoid: two bouncing at once, a sticker with words that
keeps moving, more than 3 colours. Check: no sticker covers another's text.

**Folder burst** (for: all-in-one apps and suites with 4–8 real features) — brutalist or pop — a CSS folder scales in,
wiggles ±5° once and opens; feature tiles (one colour each, a glyph from `lottie {query}` or simple SVG, the real name
on a pill) fly out 110 ms apart onto an ellipse (from cos and sin), landing on LAND; a thin orbit drawn once the last
lands; the folder shrinks into the product mark. Avoid: invented feature names, tiles crossing the logo. Check: every
label on screen and readable.

**Bracket pointer** (for: technical SaaS, analytics) — tech — four L-shaped corners slide from the frame's corners onto
the first target (700 ms MOVE, 30 ms apart), then each moves in ONE at() with held stops to the next target (headline,
product card, key number, logo), a small label riding the top corner; the card zooms 1.2× toward the metric as the
corners tighten and the num counts. Avoid: corners left framing nothing, scan lines, an unsourced metric. Check: even
padding round each target; no text under a corner.

**Panel wipes** (also: shutter bands, smooth wipes) (for: punchy promos of 4–6 strong words, offers) — bold or swiss,
three flat colours — the cut happens under cover: a clip of its own at the root spanning the seam, above both scenes,
holds one panel with a 90 px rounded leading edge (550 ms MOVE), or six bands sliding in from alternating sides (320
ms, 35 ms apart) and out the other way; the next words ride 100 ms behind the edge and build a row at a time. Avoid: a
held word that moves, a third colour in a scene. Check: the cover is complete at the cut.

**Manifesto** (for: teasers that argue in big words: problem, turn, product) — riso or pop on warm paper — the hook
names the category or the brand; a halftone dot field pours into one big dot carrying the first line (600 ms); lines
build word by word 110 ms apart on POP; oversized braces in the accent clamp a list (mirrored in Arabic); the product
name lands last in its scene, a ring drawn round it. Avoid: blurred or pulsing dots, lines over 8 words, more than one
number. Check: what is sold is named by 2 s.

**UI story** (also: flat card explainer) (for: how a SaaS tool works in 3–4 steps) — minimal or brutalist — 6–8 flat
windows with the product's real labels pop across the frame (the problem); `promo-reel`'s cursor arrives and they fly
into one stack (600 ms MOVE, 50 ms apart); the stack opens into the product view; the cursor drags one item to its
next state, `lottie:accent-check` lands; the call to action over an underline drawn in 500 ms. Avoid: tiny unreadable
UI, more than one cursor action a step. Check: the cursor reaches each target before it acts.

**Assistant tour** (for: an AI assistant, copilot or chat feature) — tech — the prompt box rises, the real request
types (Latin `type`, Arabic `words`), the cursor presses send (`promo-reel`'s press), the answer card tilts up
(`motion-design` §7 3D tilt-in, from 28°), its lines 300 ms apart; one screen a feature. Avoid: an orb, a pastel
gradient, an answer the product cannot give, more than 5 features in 30 s. Check: the typing ends before the cut.

**Title cards and phones** (for: mobile app launches, store videos) — pop or warm, a coral accent — `accent-bg` title
cards (words `rise`, then still; hard cuts) alternating with `card` scenes holding the real app in a phone
(`promo-reel`'s UI demo); three phones may fan in from left, centre and right 100 ms apart, then hold; the last card
slides away onto the app (500 ms MOVE). Avoid: a tap ripple, a floating phone, a rating or store the person did not
give. Check: each title card reads in under a second.

**Layout reflow** (for: responsive tools, design systems, multi-platform apps) — swiss or tech, navy with a ≥15% grid —
the opening hl (set to none) snaps out of a streak (`scaleX(2.4) scaleY(.08)`→`none`, 550 ms LAND); the same three
cards in a device outline move between desktop, tablet and phone layouts in ONE at() per card with held stops (700 ms
MOVE, 50 ms apart, 1.2–1.6 s holds), a layout label after each move. Avoid: wording that changes between layouts, a
platform not supported. Check: no text clipped during a move.

**Duotone cards** (for: launches and offers with 3–5 strong photos) — editorial or riso in two tones — the person's
photos on 3:4 cards with `data-color-grading='{"preset":"mono-clean"}'` and a tint layer in the dark tone
(`mix-blend-mode: multiply`) over each; cards slide in tilted ±10–16° (600 ms LAND, 150 ms apart); a circular wipe
changes the ground while the cards regroup; for a number, the cards go to the corners as the num counts. Avoid: text
on a card, full-colour photos beside duotone ones. Check: the number matches its source.

**Flat beat** (for: consumer apps, courses, teasers on an upbeat track) — bold or pop — `music {query, length}` first;
one flat ground and one word or shape a cut, every cut on a beat; vary the entrance (a pop from 1.25 or .6 on SPRING,
Latin letters rising 40 ms apart, one drop on BOUNCE); a list builds on beats over one colour; the wordmark ends still
≥1.5 s. Avoid: a cut off the beat, more than 3 words a cut, a final pulse. Check: each word ≥0.5 s, the key line ≥1 s.

**Push-through type** (for: teasers and one-liners) — bold or swiss on paper — each layer of 2–3 words lands (scale
.6→1, 500 ms LAND), holds still ≥1 s, then the camera rushes through it (scale 1→8, 400 ms LEAVE; through a letter's
counter when Latin allows); the next layer is already landing behind (200 ms overlap); the end card ≥2 s. Avoid: a blur
of your own, a push that reverses, a cut instead of a push. Check: no frame empty.

## Product ads (the product's own pictures; load `promo-reel`)

**Light and shadow** (for: skincare, fragrance, candles, homeware) — luxe or editorial, `--look-bg: #E6D3B6` — the
product cut-out (60–70% of the height, `data-grade="none"`) on a CSS plinth; blind stripes (`repeating-linear-gradient
(115deg, …)`, multiply, blur 9 px) and a sun patch travelling 200–260 px over the scene, the cast shadow skewing with
them; a leaf silhouette swaying ~2°; the set pushing 1→1.08; copy in the first 2 s, then still. Avoid: harsh black
shadows, several light directions. Check: label and shape unchanged; shadows fall one way.

**Splash** (also: juicy splash, ingredients floating) (for: drinks, snacks, sauces, fresh food) — pop or warm — a stock
splash under the pack (`footage {stock: "orange juice splash slow motion"}`, muted, its best stretch); the pack cut-out
rises (700 ms LAND) and holds; the person's ingredient cut-outs burst out (`motion-design` §7 burst ease) and drift at
three depths; the flavour name lands at the peak; the last 1.5 s still. Avoid: an ingredient the product lacks, liquid
over the label. Check: the label reads at the peak.

**Flat lay** (for: ranges, kits, bundles, what's in the box) — swiss or pop — two or three colour blocks split on a
diagonal (`clip-path: polygon`); top-down cut-outs drop in (scale 1.06→1, the shadow tightening, 400 ms, 300 ms apart),
props after their product at fixed rotations (±12°), 01 02 03 beside each; the set pushes 1→1.04; name and price last,
held ≥1.5 s. Avoid: a prop over a label, invented flavours or prices. Check: the whole set uncropped in the last frame.

**In hand** (for: small products in recommendation posts) — pop — the person's clip or photo of the product in a hand
on a saturated ground (or their cut-out on `accent-bg`); 2–4-word tags on white pills popping beside it (250 ms, 500 ms
apart); the name and one call to action held 1.5 s. Avoid: more than 4 tags, a claim not given. Check: no tag covers
the label.

**Dark reveal** (also: dark premium poster, relight, halo) (for: perfume, audio, watches, premium hardware, limited
editions) — luxe (gold) or cinematic; tech (cyan) for hardware — frame 0 already shows the product's lit edge and the
hook words; then ONE of: a spotlight pool rising over 1 s and one sheen (`promo-reel`'s product reveal); a soft beam (a
blurred band, `mix-blend-mode: screen`, masked by the product image) passing twice, then the frame flooding with its
colour (300 ms) and holding; a ring drawn round the hl tilting into a floor ellipse (`rotateX(75deg)`, 1 s MOVE) as the
product rises into it. The name `track-in` (Latin). Avoid: a black frame 0, glow on everything, flashes over 3 a
second. Check: specs from the official sheet; the silhouette reads on the dark.

**Sculpted set** (for: beauty, wellness, design-led products sold on mood) — minimal or luxe in one stone tone — CSS
forms: spheres (`radial-gradient` lit from the top left), arches, steps, thick round SVG tubes, each turning 5–10° over
the scene; the product rises from behind a form or a sphere rolls aside (1 s MOVE); one big thin word behind the
product in a tone of the set; line icons last. Avoid: more than two hues, a form over the label. Check: the word sits
behind the product.

**Colour pop** (also: comic pop) (for: offers, flavour launches, youth app launches) — pop — two clashing brights on
off-white, or comic primaries with black outlines and Ben-Day dots (≥15%); the hl slams word by word (scale 1.3→1, 220
ms; a 5 px stroke on Latin only); rays (`conic-gradient`) turning 20–30° behind the product, which pops up from the
bottom; `lottie:accent-arrow` callouts; comic: a new ground each cut, speech bubbles and starbursts (`clip-path:
polygon`); the end still ≥2 s. Avoid: a fake discount (prices: `template` sale-promo), a wiggle on the end card. Check:
the headline reads in under a second.

**Before and after** (for: cleaning, beauty, haircare, tools, fix-it products) — warm, luxe or bold — the person's
before and after, same angle and light (clips with `data-match="none"`, so matching does not even out the difference;
photos with the same grade); before 1–1.5 s, the product in use 1.5–2.5 s, then the after opens from the start side
(`clipPath: inset(0 100% 0 0)`→`inset(0 0 0 0)`; Arabic `inset(0 0 0 100%)`; 1 s MOVE) with a 4 px white divider; قبل /
بعد (BEFORE / AFTER) labels; `lottie:accent-check`; the result line held 1.5 s. Avoid: a result bigger than the product
claims. Check: framing matches within 5%; labels clear of the change.

**Hidden feature** (for: an appliance, gadget or app feature people miss) — any look, footage-led — frame 0 is the
product in its place with the hook (4–8 words, hl set to none, top band); a push on the control (scale on the
`<video>`, 700 ms MOVE), `lottie:accent-circle` as the finger arrives, the press held ≥0.6 s; a cut to the result; step
chips and the result line 300 ms apart. Avoid: more than 3 steps, text over the finger. Check: a viewer could repeat it
after one watch.

**Step by step** (for: product how-tos of 3–5 steps) — warm (kitchen, home) or minimal — a wide shot, then a close-up a
step (a 600 ms push, held while the action happens, 2–3 s a step); a big step number (a `num` set to none) rolling in a
slot window on each cut; a progress bar, one segment a step, filling linear (from the right in Arabic); a caption pill
≤7 words; the result wider with a done chip. Avoid: a bar past its end, a step out of order. Check: each caption reads
twice before the cut.

**Mystery box** (for: drops, giveaways, gift guides) — pop — the hook names the brand or category ("Which one holds our
new oud?"); 2–4 kraft boxes (CSS, a "?" sticker); a highlight hops between them on `steps(1, end)` and lands; the
chosen box shakes ~1 s with growing amplitude (±2°→±8°); the lid pops with `lottie:accent-burst` and
`lottie:accent-confetti`; the product lifts out, its name and a real price swing in. Avoid: a fake prize or price, a
reveal after 6 s. Check: the suspense is under half the length.

