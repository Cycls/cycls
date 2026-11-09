---
name: motion-design
description: How everything moves — what a look's text presets do and when data-anim changes them, what at() is still for, easing and timing, effects the presets lack (Arabic-safe), element and camera recipes, seams, sound on the cut.
---

# motion-design — motion with intent

Load it with `video-direction` (the look) and the skill for the kind of video. The look moves the text; you move
everything else. Copy the `at()` lines and change the ids, times and colours.

## 1. What makes a video look generated

- the same ease and length on everything, every element fading and sliding up from below
- everything entering at 0 ms of its scene, all at once
- titles that keep breathing, floating or creeping after they land
- every scene entering the same way; scenes that start from rest and end at rest, like slides
- motion with no cause: things appear, nothing makes them appear

Instead: vary eases and speeds on purpose, stagger by importance, land each title and hold it **dead still**
(the world behind it or the camera keeps moving), and hand each scene to the next with a move.

## 2. The look moves the text; you move the rest

Every text role (kicker, hl, sub, num, tag, cta, quote, by, body, brand, meta) comes in by itself at its own
moment in its scene, on the look's own spring, and in the looks with an exit fades out 0.3 s before its scene
ends. Seconds from the scene's start:

| look | kicker | hl | sub | cta | exit | seam |
|---|---|---|---|---|---|---|
| editorial | fade-up 0.15 | rise 0.35 | fade-up 1.05 | fade-up 1.3 | fade | fade 0.6 |
| bold | wipe 0 | rise 0.08 | fade-up 0.45 | pop 0.5 | none | cut |
| minimal | fade-up 0.1 | wipe 0.25 | fade-up 0.75 | slide 1.0 | none | fade 0.35 |
| cinematic | track-in 0.3 | blur-in 0.6 | fade-up 1.5 | fade-up 1.6 | fade | light-leak 0.9 |
| tech | type 0.1 | blur-in 0.35 | fade-up 0.85 | pop 1.1 | fade | cinematic-zoom 0.5 |
| warm | fade-up 0.1 | words 0.3 | fade-up 0.95 | pop 1.2 | fade | fade 0.5 |
| luxe | track-in 0.2 | blur-in 0.5 | fade-up 1.4 | fade-up 1.6 | fade | fade 0.9 |
| pop | pop 0.05 | pop 0.2 | words 0.7 | pop 0.9 | none | whip-pan 0.35 |

A num counts up at 0.05–0.5 s, a brand arrives at 0.05–0.4 s, a meta comes last (0.75–2 s).

- **data-anim** changes one element's entrance when the beat's verb is not the look's: `pop` for a word that
  slams, `words` for a line read as it is said, `highlight` to sweep a marker under the `<em>`, `type` for a
  prompt, `wipe` for a line written across, `track-in` (Latin) for a title that locks in, `count` for a number.
  `data-anim-delay="1.2"` (seconds from the scene's start) beside it puts it on a beat or on the voice's word;
  alone, without a data-anim, the delay is not read. An element with its own data-anim gets no exit. Every
  preset is safe in Arabic: rise and words go by word, `type` goes by word, `track-in` becomes fade-up.
- **Never at() on an element with a role class**: two animations fight over its opacity and transform. To move
  one yourself, give it `data-anim="none"` first; the look still styles it and it is yours:
  ```html
  <h1 id="hook" class="hl" data-anim="none">Make it <em>move</em></h1>
  ```
  `at("#hook", [{ transform: "scale(1.14)" }, { transform: "none" }], 0, 650, LAND);` (on screen at frame 0,
  settling). Spans inside it are yours too: `<h1 class="hl" data-anim="none"><span id="w1">Make</span> <span
  id="w2">it</span> <em id="w3">move</em></h1>`, then one at() per span.
- **A number the preset cannot count.** `count` takes one whole number of up to six digits with what goes round
  it (87%, 3x, +350, SAR 51); anything else (1.2M, 6:30, 590,000, Arabic-Indic digits, a count down) only fades up.
  Your own counter, on a num set to none:
  ```css
  @property --n { syntax: "<integer>"; initial-value: 0; inherits: true; }
  #total { counter-reset: n var(--n); }
  #total::after { content: counter(n, arabic-indic) "٪"; }   /* counter(n) ",000" for thousands */
  ```
  `<div id="total" class="num" data-anim="none"></div>` and `at("#total", [{ "--n": 0 }, { "--n": 68 }], 300, 1400, LAND);`
- **at() is for everything that is not a role**: motifs, shapes, lines, bars and rings, a photo or a clip
  pushing, a product, a cursor, a badge, a chip, spans inside a role set to none. Text you build yourself takes
  the look's variables (`font-family: var(--look-display)`, `color: var(--look-accent)`).

## 3. How at() behaves — read before writing

- **One element a call** (the first match). Give every animated element an id; stagger with a loop:
  `const RISE = [{ opacity: 0, transform: "translateY(70px)" }, { opacity: 1, transform: "none" }];`
  `["#w1", "#w2", "#w3"].forEach((s, i) => at(s, RISE, 200 + i * 90, 650, LAND));`
- **The first keyframe is held from the scene's start.** An element that enters at 2 s sits on its first
  keyframe until then: give that keyframe `opacity: 0` unless it should be seen waiting.
- **A second animation of the same property on the same element gives ONLY its end keyframe**:
  `at("#badge", [{ opacity: 0, transform: "translateX(120px)" }], -600, 400);` moves on from wherever the
  entrance left it. A two-keyframe exit holds its first frame from the scene's start and wipes the entrance.
- **Loops and ambient motion on an element that also enters**: animate a separate property: `translate`,
  `rotate` or `scale` combine with `transform` instead of replacing it.
- **Holds and loops are keyframes**: `offset` (0–1) places a keyframe, and a keyframe's own `easing` shapes the
  stretch after it. Loops are generated, never random:
  `const k = []; for (let i = 0; i <= 8; i++) k.push({ rotate: (i % 2 ? 3 : -3) + "deg", easing: "ease-in-out" }); at("#badge", k, 0, 6000, "linear");`
- `Math.cos`, `Math.sin` and arithmetic on the index are fine; never `Math.random`.
- Marks the checks need: decorative text (ghost words, tickers) `data-layout-ignore aria-hidden="true"`;
  anything that runs outside its box or the frame on purpose (a ticker, a Ken Burns picture, a slot-machine
  column, a pan strip, a ring off the edge) `data-layout-allow-overflow`.
- A motif under a scene's text: the scene gets a z-index (`#s1 { z-index: 1 }`), the motif `position: absolute;
  z-index: -1`. Without the scene's z-index, -1 goes behind the whole video.
- Text on a saturated ground still needs 3:1: cream on `#ff5a36` is 2.9 and warns; deepen the ground or use
  dark text.

## 4. Easing palette

The roles have the look's springs. These are for what you animate:

| name | string | use |
|---|---|---|
| land | `cubic-bezier(0.16, 1, 0.3, 1)` | arrivals: fast, then a long settle. The default entrance |
| glide | `cubic-bezier(0.25, 1, 0.5, 1)` | softer, premium arrivals |
| move | `cubic-bezier(0.65, 0, 0.35, 1)` | from one place to another; wipes, draws, pans |
| drift | `cubic-bezier(0.45, 0, 0.55, 1)` | camera pushes, colour floods, slow loops |
| leave | `cubic-bezier(0.7, 0, 0.84, 0)` | exits, zoom-throughs: it accelerates away |
| pop | `cubic-bezier(0.34, 1.56, 0.64, 1)` | a small overshoot: icons, badges, stickers |
| spring / soft / bounce | below | playful dots (20% overshoot) / cards, bars (5%) / a drop that lands, once |
| `steps(1, end)` | | on/off: a word appearing, a cut inside a scene |
| `linear` | | rotation, tickers, Ken Burns, a fade beside a bouncing move |

```js
const LAND = "cubic-bezier(0.16, 1, 0.3, 1)", GLIDE = "cubic-bezier(0.25, 1, 0.5, 1)", MOVE = "cubic-bezier(0.65, 0, 0.35, 1)";
const DRIFT = "cubic-bezier(0.45, 0, 0.55, 1)", LEAVE = "cubic-bezier(0.7, 0, 0.84, 0)", POP = "cubic-bezier(0.34, 1.56, 0.64, 1)";
const SPRING = "linear(0, 0.121, 0.393, 0.697, 0.952, 1.12, 1.196, 1.199, 1.157, 1.095, 1.036, 0.991, 0.966, 0.958, 0.962, 0.974, 0.986, 0.997, 1.005, 1.008, 1.008, 1.007, 1.004, 1.002, 1, 0.999, 1)";
const SOFT = "linear(0, 0.116, 0.352, 0.594, 0.79, 0.924, 1.001, 1.037, 1.046, 1.041, 1.03, 1.019, 1.01, 1.003, 1, 0.998, 0.998, 0.998, 0.999, 0.999, 1)";
const BOUNCE = "linear(0, 0.061 9%, 0.245 18%, 0.551 27%, 1 36.4%, 0.819 45%, 0.75 54.5%, 0.813 63.6%, 0.931 70%, 0.955 77%, 0.938 81.8%, 0.951 86%, 1 90.9%, 0.985 95%, 0.988 97.7%, 1)";
```

- Arrivals land on a long tail; exits accelerate; a move between two places eases both ways.
- **Position and size may overshoot; opacity, colour and blur never do.** With a spring or pop, fade on its own
  `linear` animation of 150–250 ms beside the move.
- The ease is the feeling: confident = land 0.5 s; luxury = glide 0.9 s; playful = spring 0.6 s; urgent = land
  0.25 s; calm = drift 1.2 s; mechanical = steps or move 0.3 s. Match the look: glide with luxe and cinematic,
  pop and spring with pop and warm, land with bold and tech.

## 5. Timing

| what | seconds |
|---|---|
| a word, an icon, a dot | 0.25–0.4 |
| a card, a panel, a chart bar | 0.5–0.9 |
| a full-frame move, a pan, a wipe | 0.6–1.0 |
| a dramatic reveal | 1.0–1.5 |
| a camera push, a background drift | the whole scene |

- Time your moves around the look's: a motif or a picture moves first (0–0.3 s), the headline lands on it, the
  supporting pieces after. The video's very first frame shows a finished composition, not a half-entered word.
- **Exits are 40–50% shorter than entrances.** Stagger: words 60–120 ms, list items 40–80 ms; the whole cascade
  under 0.5 s.
- **Order is importance**: the hero moves first and furthest; supporting pieces move less, later, subtler.
  Everything in one group comes from one direction (Arabic: mirror it).
- **Stillness before the payoff**: 0.3–0.75 s of nothing new just before the big number or the reveal.
- **Nothing on screen still for more than ~0.6 s**: once the words are landed, the camera, the ground or the next
  reveal moves. A 30 s video is about 12–15 compositions with beats of 1.4–3.5 s.
- Render at 30 (the default): a final of 30 s or less is drawn with motion blur by itself, as a camera sees fast
  moves; never fake it with a blur on a fast move. `fps: 60` only when the person asks for it, or for a screen
  recording or UI demo (smoother, no blur, twice the render time).

## 6. Text effects the presets don't have

The presets cover word rise (`rise`), blur-in, fade-up, mask reveal (`rise` in Latin), the handwriting wipe
(`wipe`, from the right in Arabic), the highlight sweep, the typewriter (`type`), tracking in and the count-up.
Build these with at() on an hl or a sub set to `data-anim="none"`, or on spans inside it:
1. **Slam** — one or two words of impact:
   `at("#slam", [{ transform: "scale(1.5)", filter: "blur(14px)" }, { transform: "scale(1)", filter: "blur(0px)" }], 500, 450, "cubic-bezier(0.7, 0, 0.2, 1)");`
   `at("#slam", [{ opacity: 0 }, { opacity: 1 }], 500, 150, "linear");` Arabic: yes, the whole word.
2. **Grey to ink** — words light up as they are said: each word span starts dim, `[{ color: "#6b6b7a" }, { color: "#f4f1ea" }]`,
   250 ms linear, 90 ms apart, no move. Keep the dim colour at 3:1 against the ground. Arabic: yes.
3. **Strike and replace** — a line crosses the old word (scaleX 0→1, 350 ms), the old word drops away
   (`[{ opacity: 0, transform: "translateY(40px)" }]`, 300 ms on LEAVE), the new word lands in the same spot
   (both spans in one `display: inline-grid` box, each `grid-area: 1 / 1`), 500 ms on land.
4. **Slot machine** — one word rolls through options: a window `display: inline-block; height: 1.12em;
   overflow: hidden; vertical-align: bottom` holding a column of words (`line-height: 1.12`, marked
   `data-layout-allow-overflow`), one animation with held stops: `{ transform: "translateY(0)", offset: 0.2 },
   { transform: "translateY(-1.12em)", offset: 0.4 }, …`, each keyframe `easing: "cubic-bezier(0.5, 0, 0.2, 1)"`.
   Ends on the real word. Arabic: yes.
5. **Split line** — two spans from opposite sides, `[{ opacity: 0, transform: "translateX(-700px)" }, { opacity: 1, transform: "none" }]`
   and the same from `700px`, 60 ms apart, 700 ms on land: a clash, "this vs that".
6. **Count-up with a punch** — your own counter (§2), then on its landing
   `at("#total", [{ scale: 1 }, { scale: 1.12 }, { scale: 1 }], 1700, 350, "ease-out");`
7. **One word a beat** — words stacked in one place (inline-grid as in 3), each shown on a beat:
   `at("#k2", [{ opacity: 0 }, { opacity: 1 }], 900, 1, "steps(1, end)");`
   `at("#k1", [{ opacity: 0 }], 900, 1, "steps(1, end)");` with a SPRING scale 0.8→1 on each arrival. Hold each
   word at least 0.4 s; on music, change on the beat.

Spans keep the role's type (they inherit it). Arabic is never split into letters.

## 7. Element and camera recipes

- **Line or path drawing**: `<path … pathLength="100" stroke-dasharray="100 120" stroke-dashoffset="110" stroke-linecap="round">`,
  `[{ strokeDashoffset: 110 }, { strokeDashoffset: 0 }]`, 1.0–1.4 s on move. Underlines, routes, arrows, signatures.
- **Bars**: `transform-origin: 50% 100%`, `[{ transform: "scaleY(0)" }, { transform: "scaleY(1)" }]`, 800 ms on
  SOFT, 80 ms apart; the bar that matters last, in `var(--look-accent)`.
- **Ring or donut**: an SVG `rotate(-90deg)`, a track circle and an arc `pathLength="100" stroke-dasharray="100 120"`,
  `[{ strokeDashoffset: 100 }, { strokeDashoffset: 100 - VALUE }]`, 1.3 s on land, the num inside counting with it.
- **3D tilt-in**: the parent `perspective: 1000px`; the card `transform-origin: 50% 100%`,
  `[{ opacity: 0, transform: "rotateX(55deg) translateY(80px)" }, { opacity: 1, transform: "rotateX(0deg) translateY(0)" }]`, 1 s on land.
- **Ken Burns / push**: the camera is the picture. A photo in a box with `overflow: hidden`, the img marked
  `data-layout-allow-overflow`: `[{ transform: "scale(1)" }, { transform: "scale(1.12) translate(-3%, -2%)" }]`
  over the scene, linear; a `<video>` is animated itself (its offsets count from its own data-start). Never wrap
  the roles to push them: push the picture or the motif behind them, 1 → 1.06 over the scene on drift.
- **Parallax**: motif layers drifting the same way over the scene, linear: the far one 20%, the middle 50%, the
  near one 100% of the distance (40, 90, 180 px): depth behind an end card or a title.
- **Burst**: ten dots `#p0…#p9` stacked at one point, fired on a payoff, a logo, a "done" (T = its moment):
  ```js
  for (let i = 0; i < 10; i++) {
    const a = i * 36 * Math.PI / 180, d = 150 + (i % 3) * 30;
    at("#p" + i, [{ transform: "translate(0, 0) scale(1)" }, { transform: `translate(${Math.round(Math.cos(a) * d)}px, ${Math.round(Math.sin(a) * d)}px) scale(0.3)` }], T, 900, "cubic-bezier(0.1, 0.8, 0.3, 1)");
    at("#p" + i, [{ opacity: 0 }, { opacity: 1, offset: 0.05 }, { opacity: 1, offset: 0.6 }, { opacity: 0 }], T, 900, "linear");
  }
  ```
- **Ticker**: one long `nowrap` row, `translateX(0)` → `translateX(-1400px)` over the scene, linear; decorative.
- **Shape morph**: keep one shape function: `[{ clipPath: "inset(0 46% 0 46% round 60px)" }, { clipPath: "inset(0 0% 0 0% round 24px)" }]`
  opens a pill into a bar or a card (900 ms on land). `circle()` to `circle()` for an iris.
- **Bloom**: when the hero lands, a radial-gradient glow behind it goes opacity 0→1 and scale 0.8→1 once (not a pulse).
- **Pan through stations**: a strip of pictures or motifs three frames wide (`data-layout-allow-overflow`), one
  animation that moves and holds: `{ transform: "translateX(0)", offset: 0.25 }, { transform: "translateX(-1080px)", offset: 0.45 }, …`,
  each keyframe `easing` MOVE. One idea a station.
- **Depth of field**: when the headline lands, blur the picture under it `blur(0px)` → `blur(14px)`, 700 ms on
  land; make it larger than the frame (`inset: -60px`) so its edges never show.
- **Counter-motion**: when the hero enters from the left, the ground drifts right 20–30% as far.

## 8. Seams between scenes

- The look puts its seam (the table in §2) into every scene that starts where another ends, unless the video
  sets a data-transition anywhere: then it adds none, and each seam is yours (a scene with none cuts). In the
  looks with an exit, the text fades out in its scene's last 0.3 s, as the seam begins.
- **Choose your own** where the story turns, 1–2 in a video: `light-leak` (warm: a launch, a memory),
  `whip-pan` (energy, the next item), `cinematic-zoom` (into a detail), `flash-through-white` (a reveal),
  `sdf-iris` (a product or a logo), `glitch` and `chromatic-split` (tech, music, a twist), `domain-warp`,
  `ripple-waves`, `swirl-vortex` (a dream, a change of world: rarely).
- **Hard cut** on a beat, in a fast list, for comic timing: bold's way, and the right one for most reels.
- **A move that carries over the cut**: what you animate keeps going: the photo pushing into the cut and the
  next one starting pushed the same way, the band sliding on, a shape leaving one scene where it enters the next.
  One direction for the video: in a left-to-right video things travel left, in an Arabic one right; up for a
  conclusion, forward (zoom) for going deeper.
- **Dip cut**: a black layer last in the outgoing scene (`position: absolute; inset: 0; background: #000`, over
  its text) goes from opacity 0 to 0.45 in the scene's last 0.1 s before a hard cut: the cut reads as meant.

## 9. Animations and pieces in the choreography

- A Lottie accent is a reaction: start it on the frame it reacts to, with `data-delay` = that moment in the scene
  (circle the number as the count lands, a check as the item lands, confetti on the payoff). One a beat.
- `motion` pieces (lower-third, logo-reveal, chart, kinetic-title) take the look's type and colours (and the
  kit's) by themselves: a lower third 0.5–1 s after a person starts talking, a logo-reveal as the last 2–3 s;
  `edit` their timing to sit on your beats.

## 10. Sound on the picture

In a video with music (or when the person wants sound), the big moves get sound effects (`sfx:<id>`, listed in
the instructions with each one's hit time): it is what separates a studio edit from a template. Silent videos
get none.

| moment | effect | data-start |
|---|---|---|
| a seam: a cut on a move, a whip, a card flying | `whoosh` / `whoosh-short` | the cut − 0.1 |
| a calm seam, a card sliding in gently, a message sent | `whoosh-soft` / `swish` | the cut − its hit |
| something arriving, then leaving | `swoosh-in`, then `swoosh-out` | the arrival − its hit |
| into the centrepiece or a GPU transition | `whoosh-cinematic` | the cut − its hit |
| a slam, the big number landing, the logo stamped | `impact-bass-1`, `drum-hit` or `stamp` | the landing − its hit |
| a dramatic title, the reveal of a launch | `stinger`; a cinematic logo in the dark: `sub-boom` | the reveal − its hit |
| the beat dropping into a reel's main part | `bass-drop` | the drop − its hit |
| the seconds before the payoff | `riser` or `drum-roll` (its rimshot is the hit), then the impact | the payoff − its hit |
| a countdown to a launch, a deadline | `countdown-beep` (the long beep is its hit), `clock-tick` under it | the launch − its hit |
| a chip, a badge, an emoji, a burst | `pop`; playful `bubble-pop`; under a voice `pop-soft` | the pop − its hit |
| a cursor press, a toggle | `click` | the press |
| text typing on | `typing`, `data-duration` = the typing | the first letter |
| a number or data point lighting up | `ping` | the moment − its hit |
| done, sent, a win | `chime`, `sparkle` or `ding` | the moment − its hit |
| a price, a sale, cashback | `cash-register`; a reward `coin-flip`; savings `coins` | the price landing − its hit |
| a photo, a product shot frozen | `camera-shutter` (`-double` for a burst), `camera-flash` | the freeze − its hit |
| a message, an order arriving | `phone-vibrate`, `notification`; an order ready `service-bell` | the moment − its hit |
| a door, a store opening, a customer | `doorbell`, `shop-bell` | the moment − its hit |
| a letter, a contract, a note | `pen-signature`, `pen-scribble`, `page-turn` | the stroke − its hit |
| a twist, "wait, what?" | `record-scratch`; a joke's punchline `ba-dum-tss` | the twist − its hit |
| a magical or premium change | `magic-shimmer`, `twinkle` | the change − its hit |
| tension before something that matters | `heartbeat` | the moment − its hit |
| a crowd's reaction to a win | `cheer`, `applause` (under the payoff, not over words) | the win − its hit |
| an Arabic or Gulf promo's cut or title | `darbuka-fill` (ends on its hit), `darbuka-hit`, `oud-pluck` | the cut − its hit |

- The hit lands on the frame it belongs to: a role's moment is its scene's start + its delay (§2 table, or your
  data-anim-delay). With music, the moment itself sits on a beat, so the effect, the cut and the music hit together.
- One for a moment that earns it, at most one every 1.5 s; the hook and the payoff get the strongest. A montage
  cut to music needs few: the music is the rhythm.
- Under a voice-over's sentence only small ones, `data-volume="0.5"`. On the end card: one impact or chime as
  the logo lands, then let the music finish.
- `<audio id="fx-slam" src="sfx:impact-bass-1" data-start="4.35"></audio>` for a slam landing at 4.45 s; the
  sound map in the reply says when each one hits: check it against your beat plan.

## 11. A reel, beat by beat (14.5 s, vertical, bold)

1. 0–2.4 s, the hook: an hl set to none, "Make" on screen at frame 0; "it", then "move." replace it one a beat
   (0.48 s); "move." is the `<em>` and slams; a burst answers its landing; a ghost word drifts behind (a motif).
2. 2.4–5.2 s: "Built for" + a slot machine rolling teams → shops → brands → "you." Hard cut on the bar line.
3. 5.2–8.4 s, accent-bg: the tag, the num counting to 87% (the look), a ring drawing around it (yours), the sub;
   a motif pushes 6% the whole time.
4. 8.4–11.4 s: a quote and its by, the look's; the photo behind it pushing (G4 in `video-direction`).
5. 11.4–14.5 s: `data-transition="whip-pan"` into the end card (the look then adds no other seam: the rest cut,
   as bold does); rings drift at three depths, the logo stamps, brand, cta and meta from the look, 1.5 s of hold.

One accent, one spring, every beat with something moving, every title landed and still. Render at 30: the motion blur comes with it.

## 12. Never

- at() on a role element without `data-anim="none"` on it; a font, a size or a colour written over a role.
- Arabic letter by letter, or letter-spacing on Arabic.
- Opacity, colour or blur that bounces; more than one bouncing thing at a time.
- Titles that keep moving once landed; breathing, floating or pulsing loops to fill time: reveal the next thing
  or shorten the scene.
- Motion under a line someone is reading; a move that ends after its scene does (land 0.3 s before the end).
- The same entrance on every scene's hero, or the same seam three times running.
