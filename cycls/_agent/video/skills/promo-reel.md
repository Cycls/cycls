---
name: promo-reel
description: Reels and promos (6–30 s, vertical first) — launches, offers, openings, invites: the safe band, first-second hooks, 6/15/30 s beat plans, tested scenes, cutting to music, Gulf occasions, campaign sizes.
---

# promo-reel — a reel that stops the thumb

Load `video-direction` (the look) and `motion-design` (the moves) with this skill. This one is what a promo
needs, in what order, and how fast.

## What a reel must do

- **Muted first.** The words and the picture carry the message; music adds energy. A voice-over suits a 30 s
  promo, not a bumper.
- **Frame 0 is the thumbnail and the hook.** The subject is already on screen and readable at 0 s: never
  black, never a logo, never an empty frame waiting for an entrance. Animate the hook FROM a visible state
  (`scale(1.14)` → `scale(1)`), not from `opacity: 0`.
- **The safe band (1080 × 1920).** Every word and the product between y 220 and y 1440 (an offer or a CTA
  sits higher still, above y 1330). Below 1440 the app draws the caption, the handle and the buttons: only
  background and texture there. Keep 140 px clear on the right (the like/share rail). Square and portrait feeds:
  the 6% margin only.
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

## Real pictures first

An agency reel is built on pictures of the thing itself — the coffee pouring, the shop's door, the product in
a hand — with type cut over them, not type on a flat ground. In this order:
1. the person's own photos and clips (`footage {path}` for a clip; photos by their workspace path);
2. stock footage of the subject: `footage {stock: "barista pouring latte art close up", orientation: "portrait"}`,
   two to four clips, words that describe a SHOT (subject, action, closeness, light), not a topic; read each
   sheet and keep the shots that match one light and one palette;
3. only when neither fits (a sale with no product, an abstract service): a type-led look from `video-direction`.

On footage:
- Each piece `muted`, 1.5–3 s, cut on the music's grid; a slow push on the `<video>` itself
  (`at("#v2", [{ transform: "scale(1)" }, { transform: "scale(1.08)" }], 0, 2500, "linear")`).
- One grade on every piece, so clips from different shoots look like one shoot:
  `video { filter: contrast(1.08) saturate(.9) sepia(.12) brightness(.95); }` (warm), or
  `saturate(.75) contrast(1.12) brightness(.9)` (cool, premium).
- Words over footage sit on a scrim (`linear-gradient(to top, rgba(10,8,6,.85) 0%, rgba(10,8,6,0) 55%)`) or on
  a solid block, never bare over a bright shot.
- The offer, the price and the end card may leave the footage for the brand's ground: a cut from picture to a
  bold flat card on the beat is itself a hit.

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

## Scenes a promo needs (each one tested)

Positions are for 1080 × 1920; `out` is `"cubic-bezier(0.16, 1, 0.3, 1)"`, `io` is
`"cubic-bezier(0.65, 0, 0.35, 1)"`.

**The hook number, readable at frame 0:**
```js
at("#pct", [{ transform: "scale(1.14)" }, { transform: "scale(1)" }], 0, 650, out);   // .pct: 440px, weight 900
at("#on", [{ opacity: 0, transform: "translateY(40px)" }, { opacity: 1, transform: "none" }], 450, 450, out);
at("#rule", [{ transform: "scaleX(0)" }, { transform: "scaleX(1)" }], 750, 450, io);  // transform-origin: right (Arabic)
```

**Product reveal:** the product rises and settles, its shadow tightens, and a light passes over it. The sheen
is masked by the product's own image, so it lights the product and not the air around it:
```html
<div id="shadow" class="shadow"></div>  <!-- 480×64, radius 50%, radial-gradient(closest-side, rgba(0,0,0,.7), transparent) -->
<div id="stage" class="stage"><img src="uploads/product.png" alt=""><div id="sheen" class="sheen"></div></div>
```
```css
.sheen { position: absolute; inset: 0; mix-blend-mode: screen;
  background: linear-gradient(105deg, transparent 38%, rgba(255,240,210,.55) 50%, transparent 62%);
  background-size: 300% 100%; background-position: 100% 0;
  -webkit-mask-image: url("uploads/product.png"); mask-image: url("uploads/product.png");
  -webkit-mask-size: 100% 100%; mask-size: 100% 100%; }
```
```js
at("#stage", [{ opacity: 0, transform: "translateY(240px) rotate(-9deg) scale(.92)" },
              { opacity: 1, transform: "translateY(0) rotate(-3deg) scale(1)" }], 300, 1100, out);
at("#shadow", [{ opacity: 0, transform: "scale(.5)" }, { opacity: 1, transform: "scale(1)" }], 300, 1100, out);
at("#sheen", [{ backgroundPosition: "100% 0" }, { backgroundPosition: "0% 0" }], 1400, 900, io);
```
Add `lottie:accent-sparkles` (data-delay 1.6, the accent colour) at the product's corner. A cut-out (PNG with
transparency, SVG) floats like this; a photo goes full-bleed with a slow zoom (`motion-design`); a screen goes in
a phone frame.

**Features as one swapping line:** the product holds and the slot below it changes. Each line enters, holds
and leaves in ONE animation (see The trap):
```js
at("#l1", [{ opacity: 0, transform: "translateY(100px)" }, { opacity: 1, transform: "none", offset: 0.4 },
           { opacity: 1, transform: "none", offset: 0.72 }, { opacity: 0, transform: "translateY(-100px)" }], 200, 800, "ease-in-out");
at("#l2", [ /* the same */ ], 950, 800, "ease-in-out");
at("#l3", [{ opacity: 0, transform: "translateY(100px)" }, { opacity: 1, transform: "none" }], 1700, 350, out);  // the last one stays
```
The slot is a box with `overflow: hidden` and room for one line (`height: 240px` at 100px type). Each line
carries `data-layout-allow-overflow`.

**The price drop:** the old price is struck, the price counts down, and the badge slams over a burst:
```html
<div class="was" dir="rtl"><b>٨٥ ر.س<i id="strike" class="strike"></i></b></div>      <!-- .strike: transform-origin right; scaleX(0) -->
<div id="now" class="now" dir="rtl"><span id="num" class="num"></span> <span class="cur">ر.س</span></div>
<div id="burst" class="lottie" data-lottie="lottie:accent-burst" data-delay="1.2" data-color="#f3c977" style="…500×500 behind the badge"></div>
<div id="badge" class="badge" dir="rtl"><small>خصم</small><span>٤٠٪</span></div>
```
```css
@property --n { syntax: "<integer>"; initial-value: 85; inherits: true; }
.num { counter-reset: n var(--n); }
.num::after { content: counter(n, arabic-indic); }   /* drop arabic-indic for Western digits */
```
```js
at("#strike", [{ transform: "scaleX(0)" }, { transform: "scaleX(1)" }], 250, 400, io);
at("#num", [{ "--n": 85 }, { "--n": 51 }], 450, 750, out);
at("#badge", [{ opacity: 0, transform: "scale(2.3) rotate(-14deg)", filter: "blur(10px)" },
              { opacity: 1, transform: "scale(1) rotate(-6deg)", filter: "blur(0)" }], 1200, 300, "cubic-bezier(0.2, 0, 0, 1)");
```
Then one line of urgency ("حتى نهاية الأحد فقط"), and only if the deadline is real.

**Proof:** five grey stars with a gold copy on top. The gold copy fills from the right in Arabic, from the
left in English, and only to the real rating:
```js
at("#gold", [{ clipPath: "inset(0 0 0 100%)" }, { clipPath: "inset(0 0 0 0%)" }], 200, 900, io);  // 4.6/5 → end at inset(0 0 0 8%)
```
Then the customer's own words (≤ 15) with their name and city. A drifting row of client logos is used only with
the person's own logo files.

**A UI demo with an oversized cursor:** an app is shown in a phone frame (560 × 1100, radius 72) at about
half the frame's width. The cursor is 110 × 165 px (an SVG arrow, white with a dark outline, a drop shadow,
z-index 30). It enters from below the frame, glides to the button and presses, and the click causes the change:
the button turns green with "✓", a ripple spreads, a cart badge pops. Then it leaves. Its whole life is ONE
animation:
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

**The end card:** use `motion {name, piece: "logo-reveal", start, vars: {logo, title, accent, background,
font, duration: 3}}` and always pass the brand's accent and background (otherwise it is navy and yellow). The
reply gives the piece's id (here `reveal-2`; its title is `#reveal-2-title`). Then `edit` the call to action into
the piece, after its title, as a pill and a handle or address:
```html
<div id="reveal-2-cta" style="position:relative; padding:14px 64px; border-radius:70px; background:#f3c977; color:#17110d; font-size:58px; font-weight:800; line-height:1.5">اطلب الآن</div>
<div id="reveal-2-url" dir="ltr" style="position:relative; font-family:'Inter', sans-serif; font-size:46px; font-weight:600; color:#c9b89c">najd.sa</div>
```
```js
at("#reveal-2-cta", [{ opacity: 0, transform: "translateY(30px) scale(.9)" }, { opacity: 1, transform: "none" }], 1150, 450, out);
at("#reveal-2-url", [{ opacity: 0 }, { opacity: 1 }], 1350, 400);
```
The call to action has settled at least 1.5 s before the video ends, and the video ends on the card.

## The trap: one element, one animation per property

When two `at()` calls animate the same property on one element, the later one wins, and because of
`fill: "both"` it holds its FIRST keyframe from the start of the scene. An exit written as a second `at()` shows
the element in its exit's start state before its entrance happens. Seen in tests: the cursor sat on the button
before it arrived, and all three swapping lines showed at once. Enter, hold and leave in ONE `at()`, using
`offset` (and a per-keyframe `easing`), put the exit on a wrapper, or give the exit ONLY its end keyframe
(`[{ opacity: 0 }]`: it moves on from wherever the entrance left it). Otherwise a second animation is safe only on
a property no other animation of that element touches: the button's press (`transform`) and its colour
(`backgroundColor`) are fine together. The cursor's press is part of its one animation.

## Cutting to music

Cutting on the beat is what makes a reel feel edited rather than assembled.

- **Pick the music before the plan.** `music {query}`: "upbeat", "tech", "playful", "corporate"; an Arabic
  flavour is "middle-eastern" (e.g. `playhouse-sound-of-arabia`, upbeat oriental house). Each track comes with its
  beat ("a beat every 0.492 s") and good places to start, each on a beat and the start of a bar.
- **Lock the grid.** `<audio src="music:<id>" data-start="0" data-media-start="<a good place>">`: the beats now
  fall at 0, then every beat (B). Plan every scene as a whole number of beats: at B = 0.492, 4 beats = 1.97 s,
  6 = 2.95 s, 8 = 3.94 s, so the cuts land at 1.97, 4.92, 6.89… Round each time to 2 decimals, never to 0.5.
- **Cut on phrases, not every beat:** every 2 beats at an energetic peak, every bar (4 beats) for corporate,
  every 2 bars with long holds for premium. The reveal, the slam and the logo land on a bar line.
- **Inside a scene,** time the entrances in beats too: `at()` offsets of 0, B, 2B (at 0.492: 0, 492, 984 ms), so
  the words land with the music even mid-scene.
- **Read it back.** After a write, the sound map lists the beats and bar lines in the video's time; a scene that
  starts off them comes back as `cut_off_beat` — move it (and what is timed inside it) onto its beat. A track
  with no steady beat: cut on the picture, scenes of 2–3 s.
- **Transitions:** hard cuts by default. Use one GPU transition into the centrepiece (`light-leak` warm,
  `whip-pan` energetic, `flash-through-white` a launch), at most one more into the end card.
- **Hits:** a burst behind the slam, sparkles on the product, `accent-confetti` only for a real win. Under a
  voice-over: `data-duck="<voice id>"`.
- **Sound effects on the cut and the slam** (`motion-design` §10): a `riser` into the reveal, `impact-bass-1` as
  the price or the logo lands, a `whoosh` on the GPU transition, a `pop` on the badge — each hitting on a beat
  (data-start = the beat − its hit). A promo with music and no effects sounds like a slideshow; a hit on every
  word sounds like a game: 4–6 in a 15 s reel.

## Gulf occasions and Arabic promos

| occasion | palette | motifs (CSS/SVG, tested) | greeting |
|---|---|---|---|
| Ramadan | night navy `#0d1b3d → #1a2c5c`, gold `#f3c977` | crescent, lantern, eight-point stars | «رمضان كريم» «رمضان مبارك» |
| Eid al-Fitr / al-Adha | cream, gold, one festive colour | confetti, sparkles, stars | «عيد مبارك» «كل عام وأنتم بخير» |
| Saudi National Day (23 Sep) | green `#006c35`, white | palms, the green field | «اليوم الوطني» + the year's count (check it) |
| Founding Day (22 Feb) | earth brown, sand, gold, deep green | Najdi triangles border | «يوم التأسيس» «يوم بدينا» |
| White Friday (late Nov) | white or black, one hot accent | a huge %, a struck price | «الجمعة البيضاء» |

- Crescent: `.moon { width: 260px; height: 260px; border-radius: 50%; box-shadow: -46px 22px 0 0 #f3c977 }`
  (the shadow is the moon; the box is empty).
- Eight-point star: two squares, the second turned 45°: `<div class="star8"><i></i><i></i></div>` with
  `.star8 i { position: absolute; inset: 0; background: #f3c977 } .star8 i + i { transform: rotate(45deg) }`.
- Najdi triangles: `background: conic-gradient(from 135deg at 50% 0, #f3c977 90deg, transparent 0) 0 0 / 60px 40px repeat-x`
  on a 40 px strip, wiped in with `clipPath`.
- Sound with an Arabic flavour: a `darbuka-fill` into the reveal (it ends on its hit), a `darbuka-hit` on a cut,
  an `oud-pluck` under the greeting or the logo — over `playhouse-sound-of-arabia` or with no music at all.
- Never draw the Saudi flag or the national emblem in a promo: the flag carries the Shahada and its
  commercial use is restricted. Use the colours.
- **Arabic copy.** Headlines ≤ 5 words in Cairo, Tajawal or Almarai at 800–900; greetings in Amiri. Put
  `dir="rtl"` on text. Motion enters from the right, a strike line grows from the right, stars fill from the
  right.
- **Numbers.** Use Arabic-Indic (٤٠٪) or Western (40%) as the brand does; a counter uses
  `counter(n, arabic-indic)`. Never put "·" next to Arabic-Indic digits: it reads as ٠ (٢٥٠ looked like ٢٥٠٠).
  Never put a minus before a percent in RTL ("-٤٠٪" scrambles): write «خصم ٤٠٪». Prices: «٥١ ر.س» or "51 SAR"
  (the new riyal sign is not in the fonts).

## A campaign in several sizes

Keep the vertical as the main size and add `data-sizes="square portrait"` for feeds (add `wide` only for
YouTube or the web). Lay each scene out as one centred flex column inside the safe band, so it holds at every
size, then loosen and resize per shape:
```css
.col { position: absolute; left: 8%; right: 8%; top: 9%; bottom: 31%; display: flex; flex-direction: column;
       align-items: center; justify-content: center; gap: 2%; text-align: center; }
#root[data-shape="square"] .col, #root[data-shape="portrait"] .col, #root[data-shape="wide"] .col { top: 7%; bottom: 7%; }
#root[data-shape="square"] .pct { font-size: 260px; }
#root[data-shape="wide"] .col.product { flex-direction: row-reverse; gap: 6%; }  /* dir=rtl: product left, words right */
```
Only scenes with a product go side by side in wide. A scene of text stays a column: as a row, its lines would be
read in the wrong order.
Check each size with `look {name, at, size: "square"}` before `render`; one render makes every size.

## Before render

Frame 0 shows the hook and the subject · every word in the safe band · one change every 1.5–3 s · the facts are
the person's · cuts on the grid · at most two GPU transitions · the end card in the brand's colours with a call
to action held ≥ 1.5 s · `look` at the hook, the reveal, the offer and the last second.
