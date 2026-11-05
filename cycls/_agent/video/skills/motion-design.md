---
name: motion-design
description: How everything moves — easing and spring strings for at(), timing and staggers, 14 text effects (Arabic-safe), element and camera recipes, seams between scenes. Load it before writing any video.
---

# motion-design — motion with intent

Load it with `video-direction` (the look) and the skill for the kind of video. Every recipe here was rendered
and checked: copy the `at()` lines and change the ids, times and colours.

## 1. What makes a video look generated

- the same ease and length on everything (0.5 s ease-out), every element fading and sliding up from below
- everything entering at 0 ms of its scene, all at once
- titles that keep breathing, floating or creeping after they land
- a fade between every scene; scenes that start from rest and end at rest, like slides
- motion with no cause: things appear, nothing makes them appear

Instead: vary eases and speeds on purpose, stagger by importance, land each title and hold it **dead still**
(the world behind it or the camera keeps moving), and hand each scene to the next with a move.

## 2. How at() behaves — read before writing

- **One element a call** (the first match). Give every animated element an id; stagger with a loop:
  `["#w1", "#w2", "#w3"].forEach((s, i) => at(s, RISE, 200 + i * 90, 650, SPRING));`
- **The first keyframe is held from the scene's start.** An element that enters at 2 s sits on its first
  keyframe until then: give that keyframe `opacity: 0` unless it should be seen waiting — a word sliding in from
  the side otherwise peeks in at the edge of the frame before its entrance.
- **A second animation of the same property on the same element gives ONLY its end keyframe**:
  `at("#title", [{ opacity: 0, transform: "translateX(120px)" }], -600, 400);` moves on from wherever the
  entrance left it. A two-keyframe exit holds its first frame from the scene's start and wipes the entrance.
- **Loops and ambient motion on an element that also enters**: animate a separate property — `translate`,
  `rotate` or `scale` combine with `transform` instead of replacing it.
- **Holds and loops are keyframes**: `offset` (0–1) places a keyframe, and a keyframe's own `easing` shapes the
  stretch after it. Loops are generated, never random:
  `const k = []; for (let i = 0; i <= 8; i++) k.push({ rotate: (i % 2 ? 3 : -3) + "deg", easing: "ease-in-out" }); at("#badge", k, 0, 6000, "linear");`
- `Math.cos`, `Math.sin` and arithmetic on the index are fine; never `Math.random`.
- Marks the checks need: decorative text (ghost words, tickers) `data-layout-ignore aria-hidden="true"`;
  anything that runs outside its box or the frame on purpose (a ticker, a mask's inner line, a Ken Burns
  picture, a slot-machine column, a pan strip, a decorative ring off the edge) `data-layout-allow-overflow`; the
  content of a scene that another scene overlaps in a seam `data-layout-allow-overlap data-layout-allow-occlusion`.
- Never `z-index: -1` inside a scene: it goes behind the whole video. Put the layer first in the markup.
- Text on a saturated accent ground still needs 3:1: cream on `#ff5a36` is 2.9 and warns; deepen the ground
  (`#e9461f`) or use dark text.

## 3. Easing palette

| name | string | use |
|---|---|---|
| land | `cubic-bezier(0.16, 1, 0.3, 1)` | arrivals: fast, then a long settle. The default entrance |
| glide | `cubic-bezier(0.25, 1, 0.5, 1)` | softer, premium arrivals |
| move | `cubic-bezier(0.65, 0, 0.35, 1)` | from one place to another; wipes, draws, pans |
| drift | `cubic-bezier(0.45, 0, 0.55, 1)` | camera pushes, colour floods, slow loops |
| leave | `cubic-bezier(0.7, 0, 0.84, 0)` | exits, zoom-throughs: it accelerates away |
| pop | `cubic-bezier(0.34, 1.56, 0.64, 1)` | a small overshoot: icons, badges, stickers |
| spring | see below | playful words and dots (20% overshoot) |
| soft | see below | premium cards, bars (5% overshoot) |
| bounce | see below | a drop that lands; once in a video |
| `steps(1, end)` | | on/off: a word appearing, a cut inside a scene |
| `linear` | | rotation, tickers, Ken Burns, a fade that runs beside a bouncing move |

```js
const LAND = "cubic-bezier(0.16, 1, 0.3, 1)", GLIDE = "cubic-bezier(0.25, 1, 0.5, 1)", MOVE = "cubic-bezier(0.65, 0, 0.35, 1)";
const DRIFT = "cubic-bezier(0.45, 0, 0.55, 1)", LEAVE = "cubic-bezier(0.7, 0, 0.84, 0)", POP = "cubic-bezier(0.34, 1.56, 0.64, 1)";
const SPRING = "linear(0, 0.121, 0.393, 0.697, 0.952, 1.12, 1.196, 1.199, 1.157, 1.095, 1.036, 0.991, 0.966, 0.958, 0.962, 0.974, 0.986, 0.997, 1.005, 1.008, 1.008, 1.007, 1.004, 1.002, 1, 0.999, 1)";
const SOFT = "linear(0, 0.116, 0.352, 0.594, 0.79, 0.924, 1.001, 1.037, 1.046, 1.041, 1.03, 1.019, 1.01, 1.003, 1, 0.998, 0.998, 0.998, 0.999, 0.999, 1)";
const BOUNCE = "linear(0, 0.061 9%, 0.245 18%, 0.551 27%, 1 36.4%, 0.819 45%, 0.75 54.5%, 0.813 63.6%, 0.931 70%, 0.955 77%, 0.938 81.8%, 0.951 86%, 1 90.9%, 0.985 95%, 0.988 97.7%, 1)";
```

- Arrivals land on a long tail; exits accelerate; a move between two places eases both ways; linear only where
  constant speed is the point.
- **Position and size may overshoot; opacity, colour and blur never do.** With a spring or pop, fade on its own
  `linear` animation of 150–250 ms beside the move.
- The ease is the feeling: confident = land 0.5 s; luxury = glide 0.9 s; playful = spring 0.6 s; urgent = land
  0.25 s; calm = drift 1.2 s; mechanical = steps or move 0.3 s. One spring family a video.

## 4. Timing

| what | seconds |
|---|---|
| a word, an icon, a dot | 0.25–0.4 |
| a headline arriving | 0.5–0.8 |
| a card, a panel, a chart bar | 0.5–0.9 |
| a full-frame move, a pan, a wipe | 0.6–1.0 |
| a dramatic reveal | 1.0–1.5 |
| a camera push, a background drift | the whole scene |

- Start a scene's first move 0.1–0.3 s in. The video's very first frame is the exception: it shows a finished
  composition (the swipe-stopper), not a half-entered word.
- **Exits are 40–50% shorter than entrances.** Stagger: words 60–120 ms, list items 40–80 ms, letters 30–60 ms;
  the whole cascade under 0.5 s. Overlap: the next element starts when the previous is 30–50% done.
- **Order is importance**: the hero moves first and furthest; supporting pieces move less, later, subtler.
  Everything in one group comes from one direction (Arabic: mirror it).
- **Build, hold, leave.** Build in the first quarter, or reveal each piece when the voice names it. Hold: a line
  to read stays 0.5 s + 0.3 s a word, the last line 2 s or more. Leave fast, or let the seam carry it out.
- **Stillness before the payoff**: 0.3–0.75 s of nothing new just before the big number or the reveal.
- **Nothing on screen still for more than ~0.6 s** across the video: if the words are landed, the camera, the
  background or the next reveal is moving. A 30 s video is about 12–15 compositions with beats of 1.4–3.5 s.
- Contrast speeds: the slowest move in a video is about three times the fastest.

## 5. Text in motion

Each effect below rendered as written; Arabic notes say how to keep the letters joined.

1. **Word rise** — the default headline. `const RISE = [{ opacity: 0, transform: "translateY(70px)" }, { opacity: 1, transform: "none" }];`
   per word on SPRING, 650 ms, 90 ms apart. Arabic: the same, by word.
2. **Blur-in by word** — elegant, no movement: `[{ opacity: 0, filter: "blur(8px)" }, { opacity: 1, filter: "blur(0px)" }]`,
   300 ms on land, 70–110 ms apart. Arabic: yes.
3. **Grey to ink** — words light up as they are said: each word starts dim, `[{ color: "#6b6b7a" }, { color: "#f4f1ea" }]`,
   250 ms linear, 90 ms apart, no position change. Keep the dim colour at 3:1 against the ground (`#6b6b7a` on
   near-black, `#8a8a95` on cream) or the check warns. Arabic: yes.
4. **Slam** — one or two words of impact:
   `at("#slam", [{ transform: "scale(1.5)", filter: "blur(14px)" }, { transform: "scale(1)", filter: "blur(0px)" }], 500, 450, "cubic-bezier(0.7, 0, 0.2, 1)");`
   `at("#slam", [{ opacity: 0 }, { opacity: 1 }], 500, 150, "linear");` Arabic: yes, the whole word.
5. **Mask reveal** — editorial: the line rises from behind an edge. Wrapper
   `overflow: hidden; padding: 0.2em 0; margin: -0.2em 0` (room for accents and descenders); the inner line,
   marked `data-layout-allow-overflow`: `[{ transform: "translateY(110%)" }, { transform: "none" }]`, 700 ms on land.
   Arabic: yes, a whole line.
6. **Handwriting wipe** — a line written across in one stroke, the best Arabic reveal:
   Arabic `[{ clipPath: "inset(0 0 0 100%)" }, { clipPath: "inset(0 0 0 0%)" }]` (opens from the right),
   Latin `inset(0 100% 0 0)` → `inset(0 0% 0 0)`; 1.0–1.4 s linear for writing, 0.6 s move for a wipe.
7. **Highlight sweep** — a marker behind one word. Markup:
   `<span id="hw" style="position: relative; display: inline-block"><span id="bar" style="position: absolute; left: -12px; right: -12px; bottom: 8px; height: 45%; background: ACCENT; transform-origin: 0 50%"></span><span style="position: relative">word</span></span>`
   then `at("#bar", [{ transform: "scaleX(0)" }, { transform: "scaleX(1)" }], 300, 500, MOVE);`
   Arabic: `transform-origin: 100% 50%`.
8. **Strike and replace** — a line crosses the old word (scaleX 0→1, 350 ms), the old word drops away
   (`[{ opacity: 0, transform: "translateY(40px)" }]`, 300 ms on LEAVE), the new word lands from above in the same
   spot (positioned absolute over it), 500 ms on land.
9. **Slot machine** — one word rolls through options: a window `height: 1.12em; overflow: hidden` holding a
   column of words (`line-height: 1.12`, marked `data-layout-allow-overflow`), one animation with held stops:
   `{ transform: "translateY(0)", offset: 0.2 }, { transform: "translateY(-1.12em)", offset: 0.4 }, …`,
   each keyframe `easing: "cubic-bezier(0.5, 0, 0.2, 1)"`. Ends on the real word. Arabic: yes (whole words).
10. **Typewriter** — Latin only, under 25 letters: each letter a span `c1…cN`;
    `for (let i = 1; i <= N; i++) at("#c" + i, [{ opacity: 0 }, { opacity: 1 }], 400 + i * 60, 1, "steps(1, end)");`
    and a caret blinking with `steps`. Arabic never letter by letter: use 6, or words with `steps(1, end)`.
11. **Tracking in** — Latin capitals: `[{ opacity: 0, letterSpacing: "0.6em" }, { opacity: 1, letterSpacing: "0.02em" }]`,
    900 ms on land. Never on Arabic: letter-spacing breaks the joins.
12. **Split line** — two lines from opposite sides, `[{ opacity: 0, transform: "translateX(-700px)" }, { opacity: 1, transform: "none" }]`
    and the same from `700px`, 60 ms apart, 700 ms on land: a clash, a comparison, "this vs that".
13. **Count-up with a punch** — the counter in the contract over 1.2–1.6 s on land, then on its landing
    `at("#count", [{ scale: 1 }, { scale: 1.12 }, { scale: 1 }], 1700, 350, "ease-out");`
14. **One word a beat** — words stacked in one place, each shown on a beat:
    `at("#k2", [{ opacity: 0 }, { opacity: 1 }], 900, 1, "steps(1, end)");`
    `at("#k1", [{ opacity: 0 }], 900, 1, "steps(1, end)");` with a SPRING scale 0.8→1 on each arrival. Hold each
    word at least 0.4 s; on music, change on the beat.

## 6. Element recipes

- **Line or path drawing**: `<path … pathLength="100" stroke-dasharray="100 120" stroke-dashoffset="110" stroke-linecap="round">`,
  `[{ strokeDashoffset: 110 }, { strokeDashoffset: 0 }]`, 1.0–1.4 s on move. Underlines, routes, arrows, signatures.
- **Bars**: `transform-origin: 50% 100%`, `[{ transform: "scaleY(0)" }, { transform: "scaleY(1)" }]`, 800 ms on
  SOFT, 80 ms apart; the bar that matters last, in the accent, with its number counting up.
- **Ring or donut**: an SVG `rotate(-90deg)`, a track circle and an arc `pathLength="100" stroke-dasharray="100 120"`,
  `[{ strokeDashoffset: 100 }, { strokeDashoffset: 100 - VALUE }]`, 1.3 s on land, the label counting with it.
- **3D tilt-in**: the parent `perspective: 1000px`; the card `transform-origin: 50% 100%`,
  `[{ opacity: 0, transform: "rotateX(55deg) translateY(80px)" }, { opacity: 1, transform: "rotateX(0deg) translateY(0)" }]`, 1 s on land.
- **Ken Burns**: the picture inside a box with `overflow: hidden`; animate the inner layer (marked
  `data-layout-allow-overflow`): `[{ transform: "scale(1)" }, { transform: "scale(1.12) translate(-3%, -2%)" }]`
  over the scene, linear. On footage, animate the `<video>` itself (its offsets count from its own data-start;
  "no script touches a `<video>`" means its playback only).
- **Parallax**: layers drifting the same way over the scene, linear — the far one 20%, the middle 50%, the near
  one 100% of the distance (40, 90, 180 px): depth behind an end card or a title.
- **Orbit**: an arm rotates 0→360deg linear around a centre; the satellite on it counter-rotates to stay upright.
- **Burst**: ten dots `#p0…#p9` stacked at one point, fired on a payoff, a logo, a "done" (T = its moment):
  ```js
  for (let i = 0; i < 10; i++) {
    const a = i * 36 * Math.PI / 180, d = 150 + (i % 3) * 30;
    at("#p" + i, [{ transform: "translate(0, 0) scale(1)" }, { transform: `translate(${Math.round(Math.cos(a) * d)}px, ${Math.round(Math.sin(a) * d)}px) scale(0.3)` }], T, 900, "cubic-bezier(0.1, 0.8, 0.3, 1)");
    at("#p" + i, [{ opacity: 0 }, { opacity: 1, offset: 0.05 }, { opacity: 1, offset: 0.6 }, { opacity: 0 }], T, 900, "linear");
  }
  ```
- **Ticker**: one long `nowrap` row, `translateX(0)` → `translateX(-1400px)` over the scene, linear; decorative marks.
- **Shape morph**: keep one shape function: `[{ clipPath: "inset(0 46% 0 46% round 60px)" }, { clipPath: "inset(0 0% 0 0% round 24px)" }]`
  opens a pill into a bar or a card (900 ms on land). `circle()` to `circle()` for an iris.
- **Bloom**: when the hero lands, a radial-gradient glow behind it goes opacity 0→1 and scale 0.8→1 once (not a pulse).

## 7. Camera

- **Push**: wrap the scene's content in one layer and scale it 1→1.06 over the whole scene on drift: a hold that
  stays alive. **Pull** (1.08→1) for an arrival.
- **Pan through stations**: a strip three frames wide (`data-layout-allow-overflow`), one animation that moves and
  holds: `{ transform: "translateX(0)", offset: 0.25 }, { transform: "translateX(-1080px)", offset: 0.45 }, …`, each
  keyframe `easing` MOVE. One idea a station.
- **Depth of field**: when the hero lands, blur the background layer `blur(0px)` → `blur(14px)`, 700 ms on land. Make
  that layer larger than the frame (`inset: -60px`) so its edges never show.
- **Colour flood**: the hero stays while the ground's `backgroundColor` changes in 0.4 s on drift: a new chapter
  without a cut.
- **Counter-motion**: when the hero enters from the left, the background drifts right 20–30% as far.

## 8. Seams between scenes

**How a scene leaves decides how the next arrives**: the same axis, the same direction, matching speed, the cut
landing mid-move on both sides. Choose one direction for the video — in a left-to-right video the content travels
left, in an Arabic video it travels right — and spend the others on meaning: up for a conclusion, forward (zoom)
for going deeper, backward for an arrival. Use 2–4 kinds of seam in a video, each with a cause; at most a third of
them hard cuts; no fades between unrelated worlds.

Set up: an opaque background on `#root` (a seam briefly shows what is behind); each scene's content in one wrapper
you animate (`#w2`), never the `.clip` itself.

1. **Cut the curve** — the default, no overlap. Outgoing, the last 0.32 s:
   `at("#t2", [{ transform: "translateX(-230px)" }], -320, 320, LEAVE); at("#t2", [{ opacity: 0 }], -220, 200, "linear");`
   incoming, from 0: `at("#t3", [{ transform: "translateX(230px)", opacity: 0.35 }, { transform: "none", opacity: 1 }], 0, 420, LAND);`
   Travel about 12% of the frame, never all the way off. Arabic video: the signs flip.
2. **Zoom-through** — deeper into the same thought. Outgoing wrapper, last 0.22 s:
   `[{ transform: "scale(1.2)", filter: "blur(10px)" }]` on LEAVE and `[{ opacity: 0.15 }]` linear; incoming wrapper:
   `[{ transform: "scale(0.75)", filter: "blur(10px)", opacity: 0.15 }, { transform: "scale(1)", filter: "blur(0px)", opacity: 1 }]`, 500 ms on land.
   Both grow. Never answer a growing exit with a shrinking entry.
3. **Inverse zoom** — an arrival, a payoff: outgoing to `scale(0.8)` + blur 10, incoming from `scale(1.25)` to 1.
4. **Blur swap** — the same stage changes state: outgoing content to `blur(12px)` in its last 0.2 s (fully opaque),
   incoming from `blur(12px)` to 0 in 0.2 s; the ground never cuts.
5. **Iris or wipe** — a new world opens from the thing that caused it (a button, a dot, a logo). The next scene
   starts `data-start="prev - 0.6"` with a higher z-index; its ground and wrapper both get
   `[{ clipPath: "circle(0% at 75% 35%)" }, { clipPath: "circle(150% at 75% 35%)" }]`, 650 ms on move. A wipe:
   `inset(0 0 0 100%)` → `inset(0 0 0 0%)`.
6. **Fly-through** — the headline or logo becomes the transition. The next scene starts `prev - 0.5` UNDER the
   outgoing one (lower z-index), already composed; the outgoing ground fades (`[{ opacity: 0 }]`, 300 ms), its
   headline scales past the camera `[{ transform: "scale(7)", filter: "blur(6px)" }]` 500 ms on LEAVE and fades in
   the last 0.18 s.
7. **Dip cut** — a black layer in the outgoing scene goes to opacity 0.45 in its last 0.1 s before a hard cut: the
   cut reads as meant.
8. **Hard cut** — on a beat, in a fast list, for comic timing, or a punch-in inside a scene (the same shot, 1.2×).

**GPU transitions** (`data-transition`) are for centrepiece moments, 1–2 in a video: `light-leak` (warm: a launch,
a memory, the brand moment), `whip-pan` (energy, the next item), `cinematic-zoom` (into a detail), `flash-through-white`
(a reveal), `sdf-iris` (a product or logo), `glitch` and `chromatic-split` (tech, music, a twist),
`domain-warp`, `ripple-waves`, `swirl-vortex` (a dream, a change of world: rarely). Write them where the story turns.

## 9. Animations and pieces in the choreography

- A Lottie accent is a reaction: start it on the frame it reacts to, with `data-delay` = that moment in the scene
  (circle the number as the count lands, a check as the item lands, confetti on the payoff). One a beat, in the
  accent colour (`data-color`).
- `motion` pieces are timed elements like any other: a lower-third 0.5–1 s after a person starts talking, a
  logo-reveal as the last 2–3 s; `edit` their timing to sit on your beats.

## 10. Sound on the picture

In a video with music (or when the person wants sound), the big moves get sound effects (`sfx:<id>`, listed in
the instructions with each one's hit time): it is what separates a studio edit from a template. Silent videos
get none.

| moment | effect | data-start |
|---|---|---|
| a seam: cut the curve, zoom-through, a whip, a card flying | `whoosh` / `whoosh-short` | the cut − 0.1 |
| into the centrepiece or a GPU transition | `whoosh-cinematic` | the cut − its hit |
| a slam, the big number landing, the logo stamped | `impact-bass-1` | the landing − 0.1 |
| the seconds before the payoff | `riser` (then the impact on the payoff) | the payoff − its hit |
| a chip, a badge, an emoji, a burst | `pop` | the pop − 0.1 |
| a cursor press, a toggle | `click` | the press |
| text typing on | `typing`, `data-duration` = the typing | the first letter |
| a number or data point lighting up | `ping` | the moment − its hit |
| done, sent, a win | `chime` or `sparkle` | the moment − its hit |

- The hit lands on the frame it belongs to, within a frame: late by a beat reads as a mistake.
- One for a moment that earns it, at most one every 1.5 s; the hook and the payoff get the strongest. A montage
  cut to music needs few: the music is the rhythm.
- Under a voice-over's sentence only small ones, `data-volume="0.5"`. On the end card: one impact or chime as
  the logo lands, then let the music finish.
- `<audio id="fx-slam" src="sfx:impact-bass-1" data-start="4.35"></audio>` for a slam landing at 4.45 s; the
  sound map in the reply says when each one hits: check it against your beat plan.

## 11. A reel, beat by beat (rendered: 14.5 s, vertical)

1. 0–2.4 s, the hook: "Make" is on screen at frame 0; "it", then "move." replace it one a beat (0.48 s); "move."
   slams in the accent and a burst answers its landing; a ghost word drifts behind. Out: zoom-through.
2. 2.4–5.2 s: "Built for" + a slot machine rolling teams → shops → brands → "you." Out: cut the curve, left.
3. 5.2–8.4 s: the eyebrow tracks in, a ring draws to 87% as the number counts, a punch as it lands, the line
   blurs in by word, a highlight sweeps "the end"; the camera pushes 6% the whole time. Out: an iris from the ring.
4. 7.8–11.4 s: the Arabic line written from the right in one stroke, underlined from the right, a small line
   blurring in. Out: the line flies through the camera.
5. 10.9–14.5 s: the end card was waiting underneath: rings drift at three depths, a bloom, the brand tracks in, a
   line draws, the tag blurs in, then 1.5 s of hold.

Four kinds of seam, one accent, one spring, every beat with something moving, every title landed and still.

## 12. Never

- Arabic letter by letter, or letter-spacing on Arabic.
- Opacity, colour or blur that bounces; more than one bouncing thing at a time.
- Titles that keep moving once landed; breathing, floating or pulsing loops to fill time — reveal the next thing
  or shorten the scene.
- Motion under a line someone is reading; a move that ends after its scene does (land 0.3 s before the end).
- The same entrance on every scene, or the same seam three times running.
