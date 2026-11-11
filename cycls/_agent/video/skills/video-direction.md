---
name: video-direction
description: The story and the look of a video, decided before the first write: the one thing, a 2 s hook, a beat plan in seconds, which of the eight looks (Gulf occasions too) and what to add on top, the brand kit, the frame, the sheet review.
---

# video-direction: the story and the look, before the first write

The contract makes a video correct, not worth watching. Left alone, every video comes out the same: the same look
picked by habit, centred text, every scene entering the same way. Before the first `write`, take the decisions
below in your head (no message, no extra call), write the plan in §2 for yourself, then write the video once.

## 1. The brief in one breath

- **The one thing**: what the viewer knows, feels or does at the end, in the viewer's words ("my coffee is
  ready when I arrive"), not the slogan.
- **Where it plays**: Reels, TikTok, Stories → vertical, often with the sound off; a feed → square or portrait;
  YouTube, a website, a screen → wide. Several places → one file with data-sizes.
- **Length**: a reel 8–20 s, an announcement 10–15 s, an explainer 30–60 s; a voice-over sets it. A length the
  person gives is a range, never padded.
- **Facts vs choices**: every claim, number, price and date on screen comes from the person or their files.
  Invent only the look and sample content; never derive a number they did not give.
- Ask at most one question, only when the message itself is missing. Otherwise decide, and name your choices
  in one line of the reply (look, length, sizes, sound).

## 2. The story

**The hook (0–2 s).** Frame 0 is the thumbnail: the ground, the picture and the first words are already there
(never an empty frame, never the logo alone); the headline reads by 0.6 s. The look brings each line in after a
delay, so the first scene's headline carries `data-anim="none"` (on screen at 0 s; move it with at() from a
visible state, `motion-design` §2). Open on the outcome in the viewer's words, a moment that creates the need, a
question with the real input in it, or the result itself. Never "Introducing…", "Meet…" or the logo first. With
the sound off, the words carry the hook. Its three layers never repeat each other: the picture, the spoken line
(5–10 words, with a voice) and the words on screen (3–7) that sharpen it. The second beat carries the hook's
premise on, never a switch to a pitch. Keep the hook inside the centred square of frame 0: feeds crop to it.

**A device and a form.** Sketch three one-line storylines (a device + a form), one bolder than your first idea,
and build the one a stranger would follow and no other company could have made. When the person asks for options, or an open brief matters, offer the
three in one short message (each: its first 2 s and its look) and wait; otherwise build yours and name the other
two in one line of the reply.
- Devices: the result first · a moment in someone's day · before / after · one real number made physical ·
  type carries the argument · a question with the input in it · one object travels through every scene.
- Forms: one continuous take (the camera pushes from one world into the next) · object to object (each scene
  ends on the thing that opens the next) · cut on the beat · one frame that rebuilds itself · split screen
  collapsing to one. Plain cuts between unrelated scenes is not a form.

**Beats** (15–40 s; under 10 s: hook → payoff → end card):

| Beat | Share | Job |
|---|---|---|
| Hook | 10–15% | the need or the result, already moving |
| Turn | ~10% | the old way failing, or the question |
| Reveal | ~10% | the product or idea named, 20–30% in |
| Proof | ~35% | 2–4 concrete things, one a beat, each with its verb |
| Payoff | ~15% | the biggest visual moment, once, 60–80% in |
| End card | 10–15% | the mark carried in, one line, the call to action; holds still ≥1.5 s |

**Rhythm.** Name it ("hook-PUNCH-proof-proof-PAYOFF-end"). Scene lengths follow the look's pace (LOOKS in the
instructions: bold 0.8–2 s, minimal 2.5–3.5 s, luxe and cinematic 3.5–6 s); something new every 2–4 s; nothing
frozen over 3 s except the end card. The look's text lands 0.3–1.6 s into its scene (luxe and cinematic
latest): a scene under about 2 s shows its headline and little else. In a scene: build (first 30%), breathe (one
slow move), resolve (land, then hold). With music, choose the track before the plan (one `music {query, length}`
call; take its pick) and write the plan in its beats: the reply gives the beat (B), and starting the track at its pick's start puts a beat at 0
and every B after it. Each scene is a whole number of beats (4 beats at B = 0.492 → 1.97 s), the payoff and the
end card land on a bar line (every 4 beats), and the plan's seconds are those beat times.

**Every element gets a verb** from the beat's idea: SLAMS, STAMPS, DROPS · SLIDES, PUSHES, WIPES · DRAWS,
FILLS, COUNTS UP, ASSEMBLES · FLOATS, DRIFTS · TYPES ON, SNAPS, LOCKS IN. No verb: not designed yet. The look
gives each text role one; when the hero's verb is another, say it with data-anim: RISES `rise` · WIPES `wipe` ·
SLAMS `pop` · TYPES ON `type` · COUNTS UP `count` · LOCKS IN `track-in` · MARKS `highlight` · word by word
`words`. What is not text (a photo PUSHES, a band SLIDES, a line DRAWS) is yours, with at().

**Copy.** At most 6 words a headline (Arabic 5), one line read at a time, no full stop on titles, no em dash (a
comma, a colon or a new line). The lines alone tell the story; so do the pictures. Never "unlock", "seamless",
"supercharge", "game-changer", "effortless", nor a denial of a claim nobody made ("not just coffee"). Arabic copy
is written as Arabic, not translated, and checked: إلى and إذا keep their hamza, ة is not ه, ى is not ي. A call to
action invites («تعرّف أكثر»، «جرّبها اليوم»): no manufactured urgency, no competitor named.

**The plan you write for yourself** (in your thinking):

```
ONE THING: قهوتك جاهزة قبل ما توصل (the order is ready when you arrive)
LOOK: warm, lang="ar"; Sadu band (G1) under every scene; --look-accent #9b2226
RHYTHM: hook-PROOF-end, 7 s, silent
| # | s       | beat  | scene              | roles (≤5 words)                          | your move              |
| 1 | 0–2.6   | hook  | card bottom        | hl قهوتك جاهزة <em>قبل</em> ما توصل (anim none) | hl settles, band runs  |
| 2 | 2.6–5.0 | proof | on-footage bottom  | kicker المحمصة · hl نحمّص كل صباح          | photo PUSHES 1 → 1.06  |
| 3 | 5.0–7.0 | end   | card               | brand سنا · cta اطلبها من التطبيق           | logo STAMPS, holds     |
```

## 3. Looks: start from one

Put `data-look="<id>"` on the root and write scenes (`clip scene`, plus top, bottom, left, on-footage, card or
accent-bg) holding the text roles: kicker, hl (a stressed word in `<em>`, when one carries it), sub, num, tag, cta, quote with by,
body, brand, meta. The look sets their type, sizes, colours, spacing and safe areas; brings each in at its own
moment and takes it out; grades footage and photos; and puts its seam between scenes. Your CSS is only what a
scene adds: a position, a picture, a motif. Never set a font, a size or a colour on a role (a font-size in its
style also stops it shrinking to fit). An Arabic video: `<html lang="ar">`, and the look turns to its Arabic
type, without tracking or italics, right to left (still dir="rtl" on its scenes, never on `<html>`).

Pick by the feeling and the occasion before the industry: a bank's Ramadan greeting is luxe in the bank's
colours. A campaign shares one look; different clients should not all get the same one.

| look | feels like | for | how it moves |
|---|---|---|---|
| editorial | considered, quiet: a serif, the stressed word in italic | brand stories, fashion, interiors, interviews | lines rise, soft fades |
| bold | loud: condensed caps, volt on black | sport, sales, drops, events | all at once, hard cuts |
| minimal | Swiss: flush to the start side, one orange | SaaS features, reports, numbers, explainers | wipes, quick dissolves |
| cinematic | film titles: tracked caps, serif italic, bars on wide | brand films, travel, documentary, teasers | late blur-ins, light leaks |
| tech | dark grid, violet glow, mono status chips | apps, AI, fintech, product demos | typed chips, blur-ins, zooms |
| warm | round serif on oat, paprika | food, cafés, hospitality, family, iftar | word by word, soft fades |
| luxe | thin capitals, champagne gold on near-black | real estate, hotels, jewellery, perfume, Ramadan, Eid | slow blur-ins, long dissolves |
| pop | stickers on yellow, hot pink | creators, tips, deals, giveaways, kids | everything pops, whip-pans |

**A direction is a look plus a motif** you add in the scene's own markup (§7):

| direction | look | add on top |
|---|---|---|
| Sadu weave: Founding and National Day, coffee, heritage | warm (luxe at night) | the woven band (G1) under every scene; accent `#9b2226`; darbuka, oud |
| Night and gold: Ramadan, Eid, weddings, invitations | luxe | a crescent, stars, a gold arch (G2); a navy ground `--look-bg: #0b1d3a` if wanted |
| Print poster: sales, launches, sport | bold | a giant numeral cut by the edge (G3); accent-bg scenes as the loud ground |
| Swiss print: results, B2B, conferences | minimal | each number its own scene; rules and bars drawn |
| Editorial page: stories, culture, case studies | editorial | a hard-edged photo in the column (`<img class="photo">`), a pull quote (quote + by) |
| Cut paper: beauty, wellness, kids, family apps | pop (loud) or warm (soft) | circles and pills with a paper shadow, cut by the edge (G6) |
| Product studio: apps, SaaS, AI | tech | the real screen in a rounded frame, the camera pushing into what matters |
| Documentary: people on footage, NGOs | cinematic | on-footage bottom titles, a lower third (`motion`), long holds |
| Neon sign: nightlife, gaming, concerts | tech (or pop) | glowing tubes and words (G5), accent `#ff2e88` |
| Annual report: banks, government, HR | minimal | the institution's colours, real photos, a `motion` chart |

Editorial is the look a generated video reaches for: pick it only for an editorial subject. Cinematic on a wide
video draws 2.39:1 bars over the frame (z-index 5): captions and anything you place over them need z-index 6+.

## 4. The brand kit wins

When the guide names a kit, still pick the look whose medium fits the feeling, then set the kit over it in your
own `<style>`, one rule, only what the kit has (its fonts by the exact family the guide gives, a catalogue family
after them):
```css
#root[data-look] { --look-accent: #0f6e4f; --look-bg: #f4efe6; --look-ink: #17130f;
  --look-display: "Brand Sans", "Cairo", sans-serif; --look-text: "Brand Sans", "Cairo", sans-serif; }
```
- `#root` makes the rule outrank the look's own, in Arabic videos too. In an Arabic video name the kit's Arabic
  family first (or an Arabic catalogue family after a Latin-only brand font).
- A dark or pale brand accent: also set `--look-on-accent` (the text on an accent-bg scene) and
  `--look-footage-accent` (the stressed word over footage) so both still read.
- The brand's video kit (the guide names it) goes in every video: its own voice (`voice: "brand"`), its music
  (`music` with no query), its own clips before stock, the logo where its intro and outro say. When the person
  wants their voice, music or logo in every video, keep it with `kit` (their consent first, for a voice).
- The composition and the motion stay the look's. The logo lands once, with weight, usually on the end card,
  carried in (wiped, stamped, a line drawing into it): never docked in a corner the whole video, never the first
  frame. A light logo needs a dark ground or a plate.

## 5. Composing a frame

- The hero fills at least 40% of the frame's height or width; a headline 60–85% of the width. A small thing in
  an empty field is not a shot: push in, crop, or give it a world.
- One focal point leads, one supports; size beats contrast beats colour beats position.
- Anchor with the scene's `top`, `bottom` or `left` (minimal is always flush to the start side), or on a band or a
  rule you add. Centring is for ceremony: an arch, an invitation, an end card.
- Three layers, no more: the ground (the look's, your motif moving slowly), the content, one accent.
- One hero move a scene; supporting moves travel 50–70% as far and start 100–200 ms later; the rest holds.
- Vertical: the look keeps a scene's text in the safe area. What you place yourself (a chip, a badge, words in a
  motif) stays between y 220 and y 1440 and out of the right 140 px, where the platforms put their names,
  captions and buttons. Decoration may go there.
- Arabic: the look mirrors its own text and entrances; what you animate, you mirror: words arrive right to left,
  a wipe opens from the right (`clip-path: inset(0 0 0 100%)` → `inset(0 0 0 0)`), a rule draws from
  `transform-origin: 100% 50%`, the first item of a comparison sits on the right. Never mirrored: play and media
  icons, clocks, check marks, logos, numbers, a chart's time axis. Arabic lines you place are centred, or stop
  140 px from the right edge (the buttons' column).
- Continuity: the ground and the carrier (a band, a rule, a colour plane) stay in place across scenes, so cuts
  feel like one move. Two or three grounds a video, changed (card → accent-bg → on-footage) only where the story
  turns; grounds that meet differ clearly in lightness. Spend the boldness in one place.

## 6. Type for video

Sizes, weights, tracking and leading are the look's, in units of the frame, so they hold at every size; a
headline too long for its line is made smaller, never broken in a word. The words are yours:
- One hl a scene, 1–6 words (Arabic 5), two lines at most; a sub is one line; three roles on screen at most.
- One idea a scene; about 0.4 s a word on screen (Arabic 0.6 s), 2 s at least.
- `<em>` on at most one word of a headline, the word that carries it (not the brand name); many headlines need
  none, and an accent on every one reads as generated.
- Arabic display without vowels: at large sizes a shadda or damma floats off and reads as a letter. Vowels belong
  in the voice-over script and in small text where a word may be misread.
- `num`: one number with what goes round it (87%, 3x, +350, 640 km). It counts up when it is one whole number of
  up to six digits; 1.2M, 6:30, 590,000 or Arabic-Indic digits need your own counter (`motion-design` §2). One kind
  of digits a video: the brand's, Western (40%) when it does not say. A Latin run inside Arabic goes in ONE
  `<span dir="ltr">` (two spans swap the words: «Claude Code» reads «Code Claude»).
- Text lands, then holds: it never drifts or shrinks while it is read (the ground may move).
- Text you set yourself (a chip, a badge, a ghost word) uses the look's variables: `font-family:
  var(--look-display)` or `var(--look-text)`, `color: var(--look-accent)`, so it belongs to the look and follows
  the kit. Read text of yours is at least 5% of the frame's height (96 px on 1920), secondary 3%; on a coloured
  ground it takes the ground's own ink, never grey.

## 7. Motifs on a look (checked on the renderer)

A motif is markup you add inside a scene and move with at(). To sit under the scene's text it needs the scene to
have a z-index and itself `position: absolute; z-index: -1` (without the scene's z-index, -1 drops it behind the
whole video). Decorative text carries `data-layout-ignore aria-hidden="true"`; shapes and pictures reaching past
the frame carry `data-layout-allow-overflow`.
```css
#s1 { z-index: 1; }   .motif { position: absolute; z-index: -1; }
```

- **G1 Sadu band**, sliding like a loom; the next scene's band starts where this one stopped:
  ```html
  <div class="sadu motif"><div class="st" style="top:14px"></div><div id="zig" class="zig"></div><div class="st" style="top:160px"></div></div>
  ```
  ```css
  .sadu { left: 0; right: 0; top: 1500px; height: 190px; background: #1a1410; }
  .sadu .st { position: absolute; left: 0; right: 0; height: 16px; background: #9b2226; }
  .sadu .zig { position: absolute; left: 0; right: 0; top: 46px; height: 80px; background-color: #f2e6cf; background-size: 80px 80px;
    background-image: linear-gradient(135deg, #9b2226 25%, transparent 25%), linear-gradient(225deg, #9b2226 25%, transparent 25%),
                      linear-gradient(315deg, #9b2226 25%, transparent 25%), linear-gradient(45deg, #9b2226 25%, transparent 25%); }
  ```
  `at("#zig", [{ backgroundPosition: "-40px 0, -40px 0, 0 0, 0 0" }, { backgroundPosition: "-248px 0, -248px 0, -208px 0, -208px 0" }], 0, 2600, "linear");`
- **G2 Night and a gold arch**: one soft glow, `radial-gradient(60% 38% at 72% 16%, rgba(245,236,215,.16),
  transparent 70%)`; stars as 6–10 layers of `radial-gradient(3px 3px at 12% 14%, #f5ecd7 50%, transparent 52%)`; a
  crescent: a 190 px circle with `border-radius: 50%; box-shadow: -38px 18px 0 0 var(--look-accent)`; an arch:
  `border: 4px solid var(--look-accent); border-bottom: 0; border-radius: 390px 390px 0 0; overflow: hidden`, rising
  with clipPath `inset(100% 0 0 0)` → `inset(0 0 0 0)`, a 260 px sheen band inside it (`mix-blend-mode: screen;
  linear-gradient(100deg, transparent, rgba(255,236,190,.35), transparent)`) crossing once. An arch holding an
  `<img>` is a window onto a photo.
- **G3 Giant numeral**, cut by the edge behind the headline:
  `<div id="ghost" class="ghost motif" data-layout-ignore aria-hidden="true">50</div>`,
  `.ghost { right: -260px; top: 120px; font-family: var(--look-display); font-size: 1100px; line-height: 1; color: var(--look-ink); opacity: .15; white-space: nowrap; }`,
  drifting `at("#ghost", [{ translate: "0 0" }, { translate: "-60px 0" }], 0, 3000, "linear");`.
- **G4 A full-bleed photo under a scene's text**: the photo is its own clip under an on-footage scene (the look
  grades it and puts the scrim; inside the scene it would cover the scrim):
  ```html
  <div id="p2" class="clip" data-start="2.6" data-duration="2.4" data-track-index="1"><img id="ph2" class="photo" src="uploads/roaster.jpg" alt="" data-layout-allow-overflow></div>
  <div id="s2" class="clip scene on-footage bottom" data-start="2.6" data-duration="2.4" data-track-index="2"><p class="kicker">From the roastery</p><h1 class="hl">Roasted <em>every</em> morning</h1></div>
  ```
  `#p2 { z-index: 1; overflow: hidden; } #s2 { z-index: 2; } #ph2 { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }`
  and `at("#ph2", [{ transform: "scale(1)" }, { transform: "scale(1.07)" }], 0, 2400, "linear");`. A photo
  inside a scene's column (`<img class="photo">` beside the text) is framed by the look.
- **G5 Neon**: `color: #fff3fb; text-shadow: 0 0 6px #ff2e88, 0 0 22px #ff2e88, 0 0 60px rgba(255,46,136,.7)` on a
  Latin word of your own (not a role; never Arabic), lit by a flicker whose keyframes each step:
  ```js
  const s = "steps(1, end)";
  at("#neon", [{ opacity: 0, easing: s }, { opacity: 1, offset: .1, easing: s }, { opacity: .15, offset: .18, easing: s },
    { opacity: 1, offset: .3, easing: s }, { opacity: .5, offset: .38, easing: s }, { opacity: 1, offset: .46 }, { opacity: 1 }], 100, 1200, "linear");
  ```
  A tube draws as an SVG path with `stroke-linecap="round" pathLength="100" stroke-dasharray="100 120"
  stroke-dashoffset="110"`, `filter: drop-shadow(0 0 10px #2de2e6)`, strokeDashoffset 110 → 0.
- **G6 Paper shapes**: circles and pills in the look's colours (`border-radius: 50%` or `999px`, background
  `var(--look-accent)`), a hard paper shadow `box-shadow: 0 22px 0 rgba(0,0,0,.12)`, cut by the frame's edge,
  popping in on a spring (scale 0.4 → 1) and drifting at different speeds.

## 8. The defaults that make a video look generated

Avoid each one unless the brand or the look's own medium uses it: a look picked by habit (editorial for
everything) · every scene the same modifier (all centred cards) · every scene entering the same way, the hero
never given its own verb · a black or navy void with small things floating in the middle · glow, orbs,
particles, lens flares as decoration · purple-to-blue gradients, mesh gradients, glass cards (a full-screen
gradient on a dark ground also bands in the MP4) · text drifting after it lands · corner brackets, frame
borders, HUD readouts as decoration · three cards in a row, a KPI grid, a title over a dimmed screenshot · the
logo first or docked in a corner · fonts, sizes or colours written over the look's roles · a motif under 15%
opacity (it vanishes in compression) · an accented word and a kicker on every scene · a bouncing button, a click
ring · a plan you would make for any similar brand.

## 9. Look at the sheet as a stranger would

After every `write`, before `render`:
1. Describe each frame in one sentence, naming what is in it. A thing you would have to explain is wrong.
2. The first cell is a finished thumbnail with the hook readable.
3. Cover the words: the pictures tell it. Read only the words: they tell it.
4. Name every default from §8 on screen and replace it from the subject, the brand or the medium.
5. Nothing you placed sits over the look's text or in the platform zones.
6. Every line long enough to read; nothing frozen over 3 s before the end card; the end card holds ≥1.5 s.
7. Count, don't guess: the accent on one thing a scene; at most two left edges a frame; grounds that meet differ
   in lightness.
8. A role missing from a frame has not come in yet (the look's delay or data-anim-delay): `look` a moment later
   before changing anything.
9. The sheet shows footage and photos graded, as the render will: judge the light, the framing and the colour
   on it.

Write each problem as one line, `t=4.2s · where · problem → exact change`, ranked: P0 breaks the read (unreadable,
wrong, a tell in the hook), P1 weakens it (a dead stretch, a soft payoff, a seam that jumps), P2 polish. Never
score the video: a score finds nothing to fix. Fix every P0 and the P1s in ONE `edit`, then `look` at the moments
you changed. When the person gives feedback, make the change it names and nothing else:

| they say | change |
|---|---|
| too fast | every zoom and pan to 0.7× its speed; nothing else |
| speed it up | shorten the beats; the later ones move up |
| the titles move | land them, then hold them dead still |
| feels like slides | enter the next scene through something on screen; cut a move mid-flight |
| too busy | remove a third of the motion; keep the moves that lead the eye |
| hard to read | fewer words, held longer (words ÷ 3 s), bigger |
