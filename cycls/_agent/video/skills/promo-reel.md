---
name: promo-reel
description: Reels and promos (6–30 s, vertical first) — launches, offers, openings, invites: the look to pick, the safe band, first-second hooks, 6/15/30 s beat plans, scenes in a look's markup, cutting to music, Gulf occasions, campaign sizes.
---

# promo-reel — a reel that stops the thumb

Load `video-direction` (the look) and `motion-design` (the moves) with this skill. This one is what a promo
needs, in what order, and how fast.

## What a reel must do

- **Muted first.** The words and the picture carry the message; music adds energy. A voice-over suits a 30 s
  promo, not a bumper.
- **Frame 0 is the thumbnail and the hook.** The subject is already on screen and readable at 0 s: never
  black, never a logo, never an empty frame waiting for an entrance. The look brings text in after a delay, so
  the hook's role carries `data-anim="none"` and you move it FROM a visible state (`scale(1.14)` → `scale(1)`).
- **The safe band (1080 × 1920).** The look keeps a scene's text clear of the app's caption and buttons; an
  offer or a call to action goes in a centred scene (`bottom` is for a title over footage). What you place
  yourself stays between y 220 and y 1440, 140 px clear of the right edge. Square and portrait: the 6% margin.
- **One message, one brand.** The headline ≤ 6 words (Arabic ≤ 5), one idea a beat, held at least
  words ÷ 3 seconds. The logo comes at the end, never first.
- **Pace.** A new beat every 1.5–3 s; nothing sits unchanged for more than ~0.6 s except the end card. A 30 s
  promo has 12–15 changes.
- **Only real facts.** Prices, dates, numbers, reviews, star ratings and client logos come from the person. Never
  invent a testimonial, a rating, "1,000+ customers" or a partner's logo: with no real proof, leave that beat out.

| goal | length | shape |
|---|---|---|
| a reminder, a retargeting ad | 6 s bumper | one message + logo |
| an offer, a launch, an invite, an opening | 9–15 s reel | hook → product → offer → end card |
| a story: why this product | 20–30 s promo | hook → desire → product → benefits/demo → proof → offer → end card |

**The look.** A sale, a drop, sport, an event: `bold` (hard cuts, built for the beat). A café, a restaurant, an
opening: `warm`. An app, AI or fintech launch: `tech`. Real estate, perfume, a gala, Ramadan, Eid: `luxe`. Deals,
giveaways, a creator's tip: `pop`. Fashion, a brand story: `editorial`. A teaser, a destination: `cinematic`.
Render a promo at 30 (the default): where type or graphics move fast, the final carries motion blur, so they read as filmed.

## Real pictures first

An agency reel is built on pictures of the thing itself — the coffee pouring, the shop's door, the product in
a hand — with type cut over them, not type on a flat ground. In this order:
1. the person's own photos and clips (`footage {path}` for a clip; photos by their workspace path);
2. stock footage of the subject, two to four clips in ONE call: `footage {stock: ["barista pouring latte art
   close up", "coffee beans roasting in drum", "cafe window morning light"], orientation: "portrait"}`, each
   search words that describe a SHOT (subject, action, closeness, light), not a topic; read each sheet and keep
   the shots that match one light (another clip for a search is `{stock: "…", pick: 1}`). One search per
   shot the reel needs (a 15 s reel has three to five shots, the end card on a card), then `write` with what
   came back: a clip near enough is trimmed to its best stretch, pushed or cropped into place, never replaced
   for a better one. Fetch again only for a shot that is plainly wrong (another subject, a watermark, words
   burnt in), and then one `pick` for that search, not a new list;
3. only when neither fits (a sale with no product, an abstract service): a card-led look (bold, pop, tech) with
   a motif from `video-direction`.

On footage:
- Each piece `muted`, 1.5–3 s, cut on the music's grid, started in the clip's best stretch and kept out of its
  weak ones (the footage reply names both); a slow push on the `<video>` itself
  (`at("#v2", [{ transform: "scale(1)" }, { transform: "scale(1.08)" }], 0, 2500, "linear")`).
- The look grades every piece and photo, and clips from different shoots are matched to each other, so they look
  like one shoot: write no `filter` of your own. A product whose colour must stay true: `data-grade="none"` on it.
- Words over footage: a scene `class="clip scene on-footage bottom"` (or `top`) with a z-index above the pieces
  (`#s1 { z-index: 10; }`); the look puts its scrim under the words.
- The offer, the price and the end card may leave the footage for a `card` or `accent-bg` scene: a cut from
  picture to a flat card on the beat is itself a hit.

## Hooks for the first 1.5 s

The hook names the subject by its second beat. Never "Introducing…" over a logo.

| pattern | on screen | English | Arabic |
|---|---|---|---|
| the number | one huge figure | "40% off everything" | «خصم ٤٠٪ على كل شيء» |
| the bold claim | 3–5 words, edge to edge | "The last coffee you'll switch to" | «آخر قهوة بتجربها» |
| the question | a question in the viewer's words | "Still paying 30 SAR a cup?" | «للحين تدفع ٣٠ ريال للكوب؟» |
| the result first | the finished thing at frame 0 | "Made in 10 minutes" | «سويناه في ١٠ دقايق» |
| before / after | a split wiped across | "Before → After" | «قبل ← بعد» |
| the swap | one slot cycles, then the answer slams | "A gift? A treat? A habit? — Najd." | «هدية؟ دلع؟ عادة؟ — نجد.» |
| the deadline | a date or a countdown | "48 hours only" | «٤٨ ساعة بس» |
| the occasion | the greeting carries the offer | "Ramadan Kareem — coffee's on us" | «رمضان كريم — والقهوة علينا» |

## Beat plans (cut lengths on the music's beat; 0.5 s without music)

**6 s bumper:** 0–2 hook that names the subject · 2–4.5 the product or the offer · 4.5–6 end card.

**15 s reel:** 0–2 hook · 2–5.5 product reveal (the centrepiece; a GPU transition into it) · 5.5–8 why: one
line that swaps three times · 8–11 the offer · 11–15 end card (logo, CTA, held ≥ 1.5 s).

**30 s promo:** 0–2.5 hook · 2.5–6 the desire or the problem (two beats) · 6–10 product reveal · 10–17 three
benefits, each shown working (2.3 s each), or a UI demo · 17–21 proof (a real number or a real review) ·
21–25 the offer · 25–30 end card.

Make each feature an action with its result, not a sentence. A list of three cards is the commonest tell of a
made video: show one at a time on the product, or as a line that swaps in a fixed slot (below).

## Scenes a promo needs

Positions are for 1080 × 1920; `LAND` and `MOVE` are from `motion-design` §4. The roles come in as the look
brings them; at() moves only what has no role class, or a role set to `data-anim="none"`.

**The hook number, readable at frame 0:**
```html
<div id="s1" class="clip scene accent-bg" data-start="0" data-duration="2" data-track-index="2">
  <div class="tag">White Friday</div><div id="pct" class="num" data-anim="none">40%</div><p class="sub">off everything until Sunday</p>
</div>
```
`at("#pct", [{ transform: "scale(1.14)" }, { transform: "scale(1)" }], 0, 650, LAND);` The tag and the sub come in
with the look. A num left to the look counts up from 0: right on a later beat, wrong at frame 0.

**Product reveal:** the product rises and settles over its shadow, and a light passes over it, masked by the
product's own image so it lights the product and not the air. The headline comes in after it lands:
```html
<div id="s3" class="clip scene card bottom" data-start="4" data-duration="3" data-track-index="2">
  <div id="shadow" class="shadow"></div>
  <div id="stage" class="stage"><img src="uploads/product.png" alt=""><div id="sheen" class="sheen"></div></div>
  <h2 class="hl" data-anim="rise" data-anim-delay="1.2">Cold brew, <em>bottled</em></h2>
</div>
```
```css
.stage { position: absolute; left: 260px; top: 260px; width: 560px; }   .stage img { display: block; width: 100%; }
.shadow { position: absolute; left: 300px; top: 1010px; width: 480px; height: 64px; border-radius: 50%;
  background: radial-gradient(closest-side, rgba(0,0,0,.7), transparent); }
.sheen { position: absolute; inset: 0; mix-blend-mode: screen;
  background: linear-gradient(105deg, transparent 38%, rgba(255,240,210,.55) 50%, transparent 62%);
  background-size: 300% 100%; background-position: 100% 0;
  -webkit-mask-image: url("uploads/product.png"); mask-image: url("uploads/product.png");
  -webkit-mask-size: 100% 100%; mask-size: 100% 100%; }
```
```js
at("#stage", [{ opacity: 0, transform: "translateY(240px) rotate(-9deg) scale(.92)" },
              { opacity: 1, transform: "translateY(0) rotate(-3deg) scale(1)" }], 300, 1100, LAND);
at("#shadow", [{ opacity: 0, transform: "scale(.5)" }, { opacity: 1, transform: "scale(1)" }], 300, 1100, LAND);
at("#sheen", [{ backgroundPosition: "100% 0" }, { backgroundPosition: "0% 0" }], 1400, 900, MOVE);
```
Add `lottie:accent-sparkles` (data-delay 1.6) at the product's corner. A cut-out (PNG with transparency, SVG)
floats like this; a photo goes full-bleed with a slow push (G4 in `video-direction`); a screen goes in a phone.

**Features as one swapping line:** the product holds and the slot changes. Simplest: one short scene per
feature (2–4 beats), the product in the same place in each, the feature its hl, cut on the beat. To swap words
inside one headline, set it to none and give each word a window in ONE at():
```html
<h1 class="hl" data-anim="none">Ready <span class="slot"><span id="l1">at home</span><span id="l2">at work</span><em id="l3">when you arrive</em></span></h1>
```
```css
.slot { display: inline-grid; }   .slot > * { grid-area: 1 / 1; }
```
```js
const win = [{ opacity: 0, transform: "translateY(.5em)" }, { opacity: 1, transform: "none", offset: 0.25 },
             { opacity: 1, transform: "none", offset: 0.75 }, { opacity: 0, transform: "translateY(-.5em)" }];
at("#l1", win, 200, 900, "ease-in-out");
at("#l2", win, 1050, 900, "ease-in-out");
at("#l3", [{ opacity: 0, transform: "translateY(.5em)" }, { opacity: 1, transform: "none" }], 1900, 400, LAND);  // the last one stays
```

**The price drop:** the old price is struck, the price counts down (the `count` preset only counts up, so the
counter is yours), and the badge slams over a burst:
```html
<div id="s4" class="clip scene card" data-start="8" data-duration="3" data-track-index="2" dir="rtl">
  <p class="sub was" data-anim="none">٨٥ ر.س<i id="strike" class="strike"></i></p>
  <div id="now" class="num" data-anim="none"></div>
  <div class="hit"><div id="burst" class="lottie" data-lottie="lottie:accent-burst" data-delay="1.2"></div><div id="badge" class="badge">خصم ٤٠٪</div></div>
  <p class="meta">حتى نهاية الأحد فقط</p>
</div>
```
```css
@property --n { syntax: "<integer>"; initial-value: 85; inherits: true; }
#now { counter-reset: n var(--n); }   #now::after { content: counter(n, arabic-indic) " ر.س"; }   /* counter(n) for Western digits */
.was { position: relative; }
.strike { position: absolute; left: 0; right: 0; top: 50%; height: 6px; background: var(--look-accent); transform-origin: right; }
.hit { position: relative; width: 500px; height: 260px; display: flex; align-items: center; justify-content: center; }   /* in the column, under the price */
.hit .lottie { position: absolute; left: 0; right: 0; top: -120px; bottom: -120px; }
.badge { position: relative; padding: 0 44px; border-radius: 24px; background: var(--look-accent); color: var(--look-on-accent);
  font-family: var(--look-display); font-size: 96px; line-height: 1.5; }
```
```js
at("#strike", [{ transform: "scaleX(0)" }, { transform: "scaleX(1)" }], 250, 400, MOVE);
at("#now", [{ "--n": 85 }, { "--n": 51 }], 450, 750, LAND);
at("#badge", [{ opacity: 0, transform: "scale(2.3) rotate(-14deg)", filter: "blur(10px)" },
              { opacity: 1, transform: "scale(1) rotate(-6deg)", filter: "blur(0)" }], 1200, 300, "cubic-bezier(0.2, 0, 0, 1)");
```
The urgency line (the meta) only if the deadline is real.

**Proof:** five grey stars with a gold copy on top that fills from the right in Arabic, from the left in English,
and only to the real rating:
```js
at("#gold", [{ clipPath: "inset(0 0 0 100%)" }, { clipPath: "inset(0 0 0 0%)" }], 200, 900, MOVE);  // 4.6/5 → end at inset(0 0 0 8%)
```
Then the customer's own words (≤ 15) as `<blockquote class="quote">` with `<p class="by">` (their name and
city): the look sets and brings them in. Client logos only from the person's own files.

**A UI demo with an oversized cursor:** the app in a phone frame (560 × 1100, radius 72) in the scene's column
under a kicker (an ordinary block, `position: relative`, so the look keeps the text clear of it). The cursor is
110 × 165 px (an SVG arrow, white with a dark outline, a drop shadow, z-index 30) inside the phone. It enters from
below, glides to the button and presses, and the click causes the change: the button turns green with "✓", a
ripple spreads, a cart badge pops. Then it leaves. Its whole life is ONE animation:
```js
at("#cursor", [
  { transform: "translate(260px, 900px) scale(1)", offset: 0, easing: "cubic-bezier(0.16, 1, 0.3, 1)" },
  { transform: "translate(0, 0) scale(1)", offset: 0.317 },
  { transform: "translate(0, 0) scale(.85)", offset: 0.36 },        // the press
  { transform: "translate(0, 0) scale(1)", offset: 0.403 },
  { transform: "translate(0, 0) scale(1)", offset: 0.767, easing: "cubic-bezier(0.7, 0, 0.84, 0)" },
  { transform: "translate(420px, 900px) scale(1)", offset: 1 }], 300, 3000, "linear");
at("#btn", [{ transform: "scale(1)" }, { transform: "scale(.95)" }, { transform: "scale(1)" }], 1250, 260, "ease-in-out");
at("#btn", [{ backgroundColor: "#231b16" }, { backgroundColor: "#2f8a4c" }], 1350, 200, "ease-out");
at("#ripple", [{ opacity: 0, transform: "scale(.2)" }, { opacity: 1, transform: "scale(.3)", offset: 0.05 },
               { opacity: 0, transform: "scale(2.2)" }], 1300, 600, "ease-out");
```
Swap the label with two stacked spans (`#add` out, `#done` in, 150–200 ms). Never fade a cursor in where it
stands. Use the person's real screens (screenshots as `<img>`), never an invented dashboard.

**The end card:** a card scene; the look sets and brings in the name, the call to action and the address, and
you carry the logo in:
```html
<div id="end" class="clip scene card" data-start="12" data-duration="3" data-track-index="2">
  <img id="logo" class="logo" src="brand/logo.png" alt=""><div class="cta">اطلب الآن</div><p class="meta" dir="ltr">najd.sa</p>
</div>
```
`.logo { height: 220px; }` and
```js
at("#logo", [{ transform: "scale(.6)" }, { transform: "none" }], 100, 600, POP);
at("#logo", [{ opacity: 0 }, { opacity: 1 }], 100, 200, "linear");
```
A `brand` line only when the logo does not say the name. The call to action settles at least 1.5 s before the
end (in luxe and cinematic it lands about 2.3 s in: give the card 4 s). A look with an exit fades the card's text
in its last 0.3 s; to end on it still, give each role its own entrance (`data-anim="fade-up"
data-anim-delay="0.8"`): a role with its own data-anim has no exit. The logo over a burst instead: `motion {name,
piece: "logo-reveal", start, vars: {logo, title}}`, in the look's type and colours.

## The trap: one element, one animation per property

A second two-keyframe `at()` on the same property holds its FIRST keyframe from the scene's start: seen in tests,
the cursor sat on the button before it arrived and all three swapping lines showed at once. Enter, hold and leave
in ONE `at()` with `offset`s, or give the exit ONLY its end keyframe (`[{ opacity: 0 }]`). Different properties
are fine (the button's press and its colour). A role already has the look's animation: `data-anim="none"` first.

## Cutting to music

Cutting on the beat is what makes a reel feel edited rather than assembled.

- **Pick the music before the plan, in one call.** `music {query, length}`: the look's first mood (or "upbeat",
  "tech", "playful", "corporate"; an Arabic flavour is "middle-eastern") and the reel's seconds. The reply names
  a pick with its start and gives its grid for that length: the beat ("a beat every 0.492 s"), scene lengths of
  4, 6 and 8 beats, and where to end on a bar. Take the pick; you cannot hear the tracks, so asking again for
  others tells you nothing.
- **Lock the grid.** `<audio src="music:<id>" data-start="0" data-media-start="<a good place>">`: the beats now
  fall at 0, then every beat (B). Plan every scene as a whole number of beats: at B = 0.492, 4 beats = 1.97 s,
  6 = 2.95 s, 8 = 3.94 s, so the cuts land at 1.97, 4.92, 6.89… Round each time to 2 decimals, never to 0.5.
- **Cut on phrases, not every beat:** every 2 beats at an energetic peak, every bar (4 beats) for corporate,
  every 2 bars with long holds for premium. The reveal, the slam and the logo land on a bar line.
- **Inside a scene,** time the entrances in beats too: a role's `data-anim` with `data-anim-delay` (0.49, 0.98),
  at() offsets (492, 984 ms), so the words land with the music even mid-scene.
- **Read it back.** After a write, the sound map lists the beats and bar lines in the video's time; a scene that
  starts off them comes back as `cut_off_beat`: move it (and what is timed inside it) onto its beat. A track
  with no steady beat: cut on the picture, scenes of 2–3 s.
- **Seams:** the look's (bold cuts hard), or one GPU transition of yours into the centrepiece (`light-leak` warm,
  `whip-pan` energetic, `flash-through-white` a launch), one more into the end card at most: once you set any
  data-transition the look adds none, and the other scenes cut.
- **Hits:** a burst behind the slam, sparkles on the product, `accent-confetti` only for a real win. Under a
  voice-over: `data-duck="<voice id>"`.
- **Sound effects on the cut and the slam** (`motion-design` §10): a `riser` into the reveal, `impact-bass-1` as
  the price or the logo lands, a `whoosh` on the GPU transition, a `pop` on the badge — each hitting on a beat
  (data-start = the beat − its hit). A promo with music and no effects sounds like a slideshow; a hit on every
  word sounds like a game: 4–6 in a 15 s reel.

## Gulf occasions and Arabic promos

| occasion | look and motif | greeting |
|---|---|---|
| Ramadan | luxe (a navy ground `--look-bg: #0d1b3d` if wanted); crescent, lantern, eight-point stars, a gold arch | «رمضان كريم» «رمضان مبارك» |
| Eid al-Fitr / al-Adha | luxe or warm; confetti, sparkles, stars | «عيد مبارك» «كل عام وأنتم بخير» |
| Saudi National Day (23 Sep) | warm or bold in green `--look-accent: #006c35`; palms, the green field | «اليوم الوطني» + the year's count (check it) |
| Founding Day (22 Feb) | warm; Najdi triangles, the Sadu band (G1 in `video-direction`) | «يوم التأسيس» «يوم بدينا» |
| White Friday (late Nov) | bold; a huge %, a struck price | «الجمعة البيضاء» |

Motifs (give the scene a z-index and each motif `position: absolute; z-index: -1` when it sits under text):
- Crescent: `.moon { width: 260px; height: 260px; border-radius: 50%; box-shadow: -46px 22px 0 0 var(--look-accent) }`
  (the shadow is the moon; the box is empty).
- Eight-point star: two squares, the second turned 45°: `<div class="star8"><i></i><i></i></div>` with
  `.star8 i { position: absolute; inset: 0; background: var(--look-accent) } .star8 i + i { transform: rotate(45deg) }`.
- Najdi triangles: `background: conic-gradient(from 135deg at 50% 0, var(--look-accent) 90deg, transparent 0) 0 0 / 60px 40px repeat-x`
  on a 40 px strip, wiped in with `clipPath`.
- Sound with an Arabic flavour: a `darbuka-fill` into the reveal (it ends on its hit), a `darbuka-hit` on a cut,
  an `oud-pluck` under the greeting or the logo — over `playhouse-sound-of-arabia` or with no music at all.
- Never draw the Saudi flag or the national emblem in a promo: the flag carries the Shahada and its
  commercial use is restricted. Use the colours.
- **Arabic copy.** `<html lang="ar">`: the look sets its Arabic type and runs right to left; `dir="rtl"` on the
  scenes. Headlines ≤ 5 words. What you animate enters from the right, a strike line grows from the right, stars
  fill from the right.
- **Numbers.** Use Arabic-Indic (٤٠٪) or Western (40%) as the brand does; a num counts up only in Western
  digits, so an Arabic-Indic count is your own counter (`counter(n, arabic-indic)`, as in the price drop). Never put
  "·" next to Arabic-Indic digits: it reads as ٠ (٢٥٠ looked like ٢٥٠٠). Never put a minus before a percent in RTL
  ("-٤٠٪" scrambles): write «خصم ٤٠٪». Prices: «٥١ ر.س» or "51 SAR" (the new riyal sign is not in the fonts).

## A campaign in several sizes

Keep the vertical as the main size and add `data-sizes="square portrait"` for feeds (add `wide` only for
YouTube or the web). The look sizes its type from the frame and keeps each size's safe area, so a scene of roles
needs no rule per size. What you placed in px (a product, a badge, a band) may: place it in % where you can, and
fix one size with a rule for it alone: `#root[data-shape="square"] .stage { top: 120px; width: 420px; }`. Only
scenes with a product go side by side in wide; a scene of text stays a column, or its lines are read in the wrong
order. Check each size with `look {name, at, size: "square"}` before `render`; one render makes every size.

## Before render

Frame 0 shows the hook and the subject · every word in the safe band · one change every 1.5–3 s · the facts are
the person's · cuts on the grid · at most two GPU transitions · no role also moved by at() · the end card's call
to action held ≥ 1.5 s · `look` at the hook, the reveal, the offer and the last second · 30 fps (motion blur on fast moves) for moving
type.
