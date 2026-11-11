---
name: explainer-video
description: Explainers, how-tos, listicles, data stories, a report or deck as a video — script and voice first, the look, a picture for every sentence, reveals on the word, diagrams that build, numbers that move, pacing.
---

# explainer-video — one idea, understood by the end

Load `video-direction` (the look) and `motion-design` (how things move) with this skill. An explainer is a guided
act of understanding, not the source read aloud over slides. Every sentence gets a picture that shows it, and each
part of that picture appears when the voice names it. The two ways it fails: the slideshow (everything on screen
at the start of a scene, then frozen) and the narrator reading the text that is already on screen.

**The look.** `minimal` for numbers, reports, processes and anything that must be clear first; `tech` for a
product, an app, AI or fintech; `editorial` for culture, history and case studies; `warm` for food, recipes and
how-tos at home. The look sets the text and moves it; you build the picture (diagrams, charts, photos) and time
both to the voice. Diagrams, charts and lines are drawn: render at 30 (fast moves get motion blur by themselves).

## 1. Before a word is written

Settle six things (in your head, or a line each to the person when the brief is vague):
- **viewer** — who, and what they already know;
- **question** — the gap or the stake the video closes ("why does my saving grow faster later?");
- **thesis** — the one line they leave with, in their words, not a slogan;
- **spine** — 3–5 steps, items or layers that build to the thesis;
- **evidence** — the real numbers, and ONE worked example that travels through every step (one amount, one
  sentence, one photo);
- **landing** — the takeaway in one line, and what to do.

Never follow the source's paragraph order: reorder, merge and cut until it teaches. Start where the viewer
already is (a person, a situation, a question they would ask), let the device that answers it enter there, and
come back to them at the end. Every figure on screen comes from the source; a number it did not give is left out
or marked "illustrative" on screen.

## 2. The script, then `voice`, then the scenes

Length comes from words: about 2 words a second in Arabic and 2.5 in English.

| Video | Arabic words | English words | Scenes |
|---|---|---|---|
| 20 s | 40 | 50 | 4–6 |
| 30 s | 60 | 75 | 6–9 |
| 45 s | 90 | 110 | 9–13 |
| 60 s | 120 | 150 | 12–16 |

- One idea a sentence, 5–12 words in Arabic, 6–15 in English. Write each sentence as cues the picture can follow
  ("first the coin, then its profit, then the profit's profit"): each cue becomes one reveal. At most about 19
  spoken words a scene (Arabic 17): trim the script, never stretch the motion.
- The first sentence is the hook. Pick one on purpose:

| Hook | Use when | Example |
|---|---|---|
| A question with the stake in it | the gap is the point | "لو ادّخرتَ ألفَ ريالٍ كلَّ شهرٍ، كم تُصبِحُ بعدَ عشرين سنة؟" |
| A number that surprises | one credible figure carries it | "90% of plastic was never recycled." |
| A belief turned over | the truth contradicts what people think | "More lanes make traffic worse." |
| Imagine | a thought experiment frames it | "Imagine money that loses value if you keep it." |
| The pain | the viewer already feels the confusion | "Everyone says diversify. Nobody says how." |
| The stake | getting it wrong costs | "Skip this step and the whole batch is ruined." |

  Never "In this video…", "مرحباً بكم", a definition, or the topic's name as the first line.
- The thesis lands by the second or third sentence; everything after it is evidence.
- Spoken style: short sentences, plain words. Say numbers the way a person rounds them ("about 590 thousand");
  the screen shows the exact figure. Set the pace with punctuation (a comma for a breath, a full stop for a
  stop) before reaching for `speed`; keep English words inside an Arabic sentence few, each one breaks its flow.
- An analogy carries one step and says where it stops ("like a snowball, except…"). A claim with limits gets
  its caveat in one line, said and shown small.
- Arabic: Standard Arabic with the default voice unless the person wants Saudi (`voice: "saudi"`). Put vowels
  on verbs and names the voice may misread (تُصبِحُ، يُرَحِّبُ), a sukun where a breath ends (فقطْ), and a comma where
  a pause belongs. `speed: 0.9–0.95` suits a calm explainer.
- Call `voice` before writing a single scene. Its reply gives every sentence's and every word's time: those
  times are the video's clock.

## 3. Pick the structure

| Structure | Beats (seconds for a 30 s video) | The stage |
|---|---|---|
| Concept | hook 3 → name the idea 3 → mechanism, one layer a sentence 3×4 → what it means 4 → takeaway 3 | one diagram that grows |
| How-to | hook 3 → step 1…4, one verb each, 4–5 s → result 4 → takeaway 3 | one stage; the object being worked on carries from step to step |
| Listicle / top N | hook 3 → N items, 3–4 s each, same layout, new picture each → wrap 3 | numbered slot that stays; contents change |
| Comparison | the question 3 → A and B side by side, 3–4 rounds → verdict 4 | a split screen, one row a round |
| Timeline / history | today 3 → the stations in order, 3 s each → back to today 4 | one long world the camera pans along |
| Data story | the number that matters 4 → where it comes from 6 → what it means 8 → takeaway 4 | one chart that builds and is annotated |
| A report or deck in 60 s | the headline result 5 → 3–4 findings 10 each → the ask 6 | the report's own pages, moved and marked up |
| Myth to fact | the belief 3 → why it seems right 6 → less wrong 6 → right, with the proof 8 → takeaway 3 | one picture corrected twice |

Pick one structure; a how-to inside a concept is fine when you name it to yourself.

## 4. A picture for every sentence

Make the picture from the content's own nouns and numbers: ask "what would this sentence look like if it were an
object?" A prop that could appear unchanged in another company's video did not come from the content.

| The sentence… | The picture |
|---|---|
| names an amount over time | a grid of dots that fills (one dot a month, a row a year), a stack that grows |
| says something grows on itself | a chain of circles, each bigger, joined by drawn arrows, the gain on each link |
| gives one big number | the number as the biggest thing on screen, counting up, with a shape that shows its size (bar, ring, filled area) |
| compares two things | a split frame, the two sides equal in size, one difference lit at a time |
| lists steps | numbered stations on one long canvas, the camera moving from one to the next |
| says "it connects to…" | a hub with nodes that pop in around it and lines drawn out to them |
| says "zoom out / the bigger picture" | open tight on one part, pull back to show the whole it sits in |
| corrects a belief | the wrong line written, struck through, the right one written over it |
| repeats a pattern ("X, Y and Z all…") | one anchor word that stays while the words beside it change |
| shows the result of a page or report | the page itself, pushed in on the line that matters, the line circled or underlined |

Make the hero 40–60% of the frame: a diagram big enough to read its labels, a number near full width. Labels sit
on the part they name and appear with it; no legends, no bullet lists, no icons in circles, no three cards in a
row, never the whole diagram at once. At most 6 parts active: the part being explained at full strength, the
context dimmed to opacity 0.35, the structure behind it 0.15. Two scenes in a row never share a layout, an
entrance and a pace.

## 5. Reveal on the word

Each element enters when the voice reaches it. With the voice at `data-start="0.5"` and a scene at
`data-start="7"`, a word the voice reply puts at 8.39 s is at 8.39 + 0.5 − 7 = 1.89 s into the scene; start the
element about 0.15 s before. A role takes its moment as a preset and a delay (the delay is read only beside a
data-anim); anything else, as an at() offset:
```html
<div id="s3" class="clip scene card top" data-start="7" data-duration="4.4" data-track-index="2">
  <p class="kicker">Compound growth</p>
  <div class="num" data-anim="count" data-anim-delay="1.74">68%</div>
  <p class="sub" data-anim="fade-up" data-anim-delay="2.9">of the gain comes in the last ten years</p>
  <svg id="curve" viewBox="0 0 1600 560" style="width: 100%; height: auto">…</svg>
</div>
```
A node of the diagram: `at("#c1", [{ opacity: 0, transform: "scale(.4)" }, { opacity: 1, transform: "none" }], 1740, 500, SPRING)`.
A diagram in the scene's column (the svg here) is laid out with the text, clear of it. Spread reveals across the
scene, most in its back half; at offset 0 show only what the first words say. A new term holds 2 s at least; the
key insight holds 3 s after it lands, nothing new beside it. A scene never opens on an empty
frame while it waits for its first word: give it the stage it will build on (the axis, the empty grid, the term in
small type), or start the scene on its first word. Hold still once everything has landed: stillness after motion
reads as confidence.

Frame 0 is the thumbnail: the hook's title is already on screen in the first frame (`data-anim="none"` on its
hl) and the first motion starts after it.

## 6. One stage across several sentences

When three sentences develop one picture (year 1 → year 10 → year 20), keep them in ONE scene and move the same
parts of the picture again (a role comes in once, as the look brings it). One element's property moves in ONE
`at()`: give its keyframes `offset`s (0 to 1 over the whole scene) and an `easing` on the keyframe where each move
starts. Two two-keyframe `at()` on the same property of one element fight: the later one's starting value shows
from the scene's first frame (a later move that gives only its end keyframe is fine: motion-design).

```js
const io = "cubic-bezier(0.65, 0, 0.35, 1)";
// the curve is revealed to year 1, then 10, then 20; each move starts on its sentence
at("#plot", [
  { clipPath: "inset(0 100% 0 0)", offset: 0 },
  { clipPath: "inset(0 100% 0 0)", offset: 0.025, easing: io }, { clipPath: "inset(0 95% 0 0)", offset: 0.094 },
  { clipPath: "inset(0 95% 0 0)", offset: 0.254, easing: io },  { clipPath: "inset(0 50% 0 0)", offset: 0.394 },
  { clipPath: "inset(0 50% 0 0)", offset: 0.556, easing: io },  { clipPath: "inset(0 0% 0 0)", offset: 0.714 },
  { clipPath: "inset(0 0% 0 0)", offset: 1 }], 0, 10650, "linear");
```

The same keyframe offsets on a counter of your own (`--y`: 0 → 1 → 10 → 20, shown as "السنة 20", on a num set
to `data-anim="none"`) keep the year in step with the curve. A word that is on, then off (a slot whose words
change: spans inside an hl set to none) is also one `at()`:

```js
const win = [{ opacity: 0, transform: "translateY(60px)" }, { opacity: 1, transform: "none", offset: 0.2 },
             { opacity: 1, transform: "none", offset: 0.8 }, { opacity: 0, transform: "translateY(-60px)" }];
at("#w1", win, 300, 800, "linear");   // each word: its own window; the anchor beside it never moves
```

## 7. Numbers that move

- A `num` counts itself up (1.4 s, then held) when it is one whole number of up to six digits with what goes
  round it (68%, 3x, +350): `data-anim="count"` and a delay land it on the word. Anything else is your own
  counter on a num set to none (the look still sizes it). Thousands, printing the zeros:
  `@property --k { syntax: "<integer>"; initial-value: 0; inherits: true; }`,
  `#total { counter-reset: k var(--k); } #total::after { content: counter(k) ",000"; }`,
  `<div id="total" class="num" data-anim="none"></div>`, `at("#total", [{ "--k": 0 }, { "--k": 590 }], 1800, 1500, LAND)`.
  Eastern Arabic digits: `counter(k, arabic-indic) "٪"` gives ٦٨٪.
- Wrap figures in Arabic text with `direction: ltr; unicode-bidi: isolate` so "240,000" keeps its order.
- Give every number a shape that shows its size: a bar (`scaleX()` from `transform-origin: left`, `right` in
  Arabic), a ring, a filled area, a grid of units. A number alone floats.
- A ring (68%):
  ```html
  <circle id="arc" cx="180" cy="180" r="150" fill="none" style="stroke: var(--look-accent)" stroke-width="28" stroke-linecap="round"
          pathLength="100" stroke-dasharray="100" stroke-dashoffset="100" transform="rotate(-90 180 180)"/>
  ```
  `at("#arc", [{ strokeDashoffset: 100 }, { strokeDashoffset: 32 }], 600, 1500, LAND)` — the offset is 100 − the percent.
- A line chart: compute the points from the real values (x by time, y by value, the axis from zero), draw the
  axis and a reference line first, then reveal the data by `clip-path: inset(0 X% 0 0)` on its wrapper (linear in
  time, unlike a dash on a curve), then mark the point that matters with a dot and a label, last. The gap between
  two lines can be a filled shape with its own label ("your profits +350,000").
- Highlight one series, grey the rest; one annotation per chart; a source line ("assuming 8% a year,
  illustrative"). No pie charts, gridlines, legends or six-number dashboards.
- An honest chart builds in this order: the question and its unit, the axes, the marks, the highlight, the
  source, then a still hold. Its title states the finding ("Sales doubled in 2025", not "Sales 2021–2025"). No
  mark passes its value on the way in, and no counter shows more precision than the source gives.
- Quick charts: the `motion` piece chart (bars or donut, in the look's type and colours by itself), `template`
  stats-reel; build your own when the chart is the story.

## 8. Diagrams that build

- **Drawn lines.** `pathLength="1" stroke-dasharray="1" stroke-dashoffset="1"` on any `<path>`, then
  `at("#k1", [{ strokeDashoffset: 1 }, { strokeDashoffset: 0 }], 2300, 500, MOVE)`: arrows, connectors, a brace,
  an outline around the point that matters.
- **Nodes.** Each pops in (scale 0.4 → 1 on a spring easing) as the voice names it, then its connector draws.
  In Arabic the chain reads right to left: the first link on the right.
- **Units that fill.** A grid of dots in one element: an empty pattern
  `background-image: radial-gradient(circle at 22px 22px, transparent 11px, rgba(255,255,255,.28) 11px 13px, transparent 13px); background-size: 44px 44px`,
  (`rgba(0,0,0,.18)` on a light look), a filled copy in `var(--look-accent)` above it revealed row by row:
  `at("#fill", [{ clipPath: "inset(0 0 100% 0)" }, { clipPath: "inset(0 0 0% 0)" }], 1650, 2200, "steps(20, end)")`.
- **Stations.** Put the steps side by side on one wide `#world` (3 × 1920 px) and move only the world, in one
  `at()` with holds: `translateX(0)` → `-1920px` → `-3840px`, each move starting on its sentence. A road line
  drawn with the same offsets ties them. Mark the world `data-layout-allow-overflow`.
- **Zoom out to the whole.** Open on one part, pull back: `transform-origin` at the part's centre (cx, cy), from
  `translate(960 − cx, 540 − cy) scale(3.2)` to `translate(0, 0) scale(1)` on an ease-out, then draw the
  connectors once the whole is in view. One zoom-out in a scene, never a zoom back in.
- **Fixed anchor.** "Cycls makes ___": the anchor never moves; the slot's words take windows (section 6).

## 9. Captions and the words on screen

- With a voice-over, add captions unless the person says not to: `<div id="cap" class="cap" data-captions="vo"
  data-cap-style="phrase" dir="rtl">` ("word" lights each word, for a punchier reel). The look sets its font and
  the said word's colour; you place and size it (`#cap { z-index: 30; … }`), low but inside the safe band (reel:
  the box's bottom edge at about y 1420, clear of the app's own caption and buttons; wide: bottom ≈ 90 px), the
  picture's text above it. A pill per line reads on anything:
  `.cap .cap-line { justify-self: center; background: rgba(0,0,0,.6); padding: .1em .55em; border-radius: .35em; }`.
- The screen carries what the ear cannot hold: the numbers, the names, the term being taught, a label on each
  part. Never the spoken sentence word for word; at most about 10 words of other text in a scene.
- The term being taught appears once, large, when first said ("العائدُ المركَّب"); then the picture takes over.

## 10. A deck, a report or a document as a video

Export its pages as JPEG with Design; make each page a scene that moves, one finding a page (`template` deck
is the plain version). A page or a screenshot is a plain `<img>`, never `class="photo"`: the look's grade is for
photographs, not a page's own colours:
- a slow push toward the line or bar that matters: `transform-origin` at that point on a wrapper around the
  image, `scale(1)` → `scale(1.12)` over the scene, the wrapper `data-layout-allow-overflow`, the frame around it
  `overflow: hidden`;
- a spotlight: an overlay `radial-gradient(circle at X Y, transparent 230px, rgba(16,20,24,.55) 300px)` fading in;
- the point drawn on: an outline (a drawn rect) or `lottie` accent-circle / accent-underline / accent-arrow, then a
  chip with the takeaway ("New market: +49m") clear of the edges.

## 11. Pacing, sound and the end

- Scenes of 2–5 s; vary them. After the biggest number, hold 0.8–1.2 s with nothing new: let it land.
- Seams: the look's between scenes, and where the story turns one with a cause you build (a zoom into the part
  being explained, the ground flooding to the next colour, a matched move: `motion-design` §8). At most one GPU
  transition of your own (cinematic-zoom, sdf-iris) into the centrepiece; once you set any data-transition, the
  look sets none and the other scenes cut, so give those cuts a matched move.
- Music only when the person wants sound: calm, corporate, inspiring or minimal-piano (`music`), with
  `data-duck="vo"` so it dips under the voice. The voice sets the cuts (between sentences); the music's beat
  only times what moves between them.
- Small sound effects carry the reveals under the voice at `data-volume="0.5"`: a `pop` as a node appears, a
  `ping` as the number lands, a soft `whoosh` on a camera move, a `chime` on the takeaway (`motion-design` §10).
- End on the one idea in one line, large, held at least 2 s, about 1 s after the voice ends; a call to action if
  there is one. A faint callback to the hook's picture behind it (the curve behind "start early") makes it land;
  faint decorative text carries `data-layout-ignore aria-hidden="true"`.
- `look` at the reveal moments: every count landed, labels clear of lines, each scene at rest at its end.

## Before you render

- The hook is a question, a number, a belief turned over — not a greeting; the thesis lands by sentence 3.
- Every sentence has its picture; nothing appears before the voice names it; no scene front-loads then freezes.
- One stage carries each run of sentences about the same picture; its moves are one `at()` per property, and no
  role is also moved by at() (set it to `data-anim="none"` first).
- Every number has a shape, a source line, and the same rounding everywhere.
- Captions in the bottom band; the screen never repeats the sentence.
- The last scene: the takeaway in one line, held.
