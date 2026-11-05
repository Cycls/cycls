---
name: footage-video
description: Load for any video made from the person's clips or stock footage: the story in the transcript, cutting on words, layouts for a wide clip in a reel, dressing a talking head, captions, sound.
---

# footage-video — the person on camera is the star

Load `video-direction` and `motion-design` with this skill for the look and the motion. This one is about
footage: choosing it, cutting it, dressing it and captioning it. Every snippet here passed the checks and was
looked at on the sheet.

## 1. Read before you cut

- `footage {path}` every clip before writing (again is free). Its reply is what you cannot see or hear: length
  and shape, shots, the sheet, and every sentence with its times. A long clip: call it again to collect.
  `tidy: true` when the person asks to tighten or clean up a talk.
- **Fix misheard words first.** Names, brands and dialect are often wrong ("ونبمح" for "ونطمح"). Change the text
  in `uploads/<clip>.words.json` and keep the times: the captions follow. Ask about a name that matters.
- **Find the story in the sentences.** Pick the best 15–45 s of a long talk, whole sentences only.
  - **Hook**: the strongest line (a result, a number, a surprise, a question) goes FIRST, even when it was said
    last. Frame 0 is the thumbnail: a face mid-sentence or a bold line, never black or a logo.
  - Then context → two or three moments → the result → an end card with one ask.
  - Cut what restates, fillers, false starts and "as you can see".

## 2. Cutting

- **A piece** begins 0.15 s before its first word and ends 0.25 s after its last; between two sentences cut in
  the middle of the pause. The next piece's `data-start` = this one's `data-start + data-duration`.
- **When a word is heard in the video** = piece `data-start` + (word time − piece `data-media-start`). Time every
  graphic and callout with it; the `write` reply's "Spoken:" line shows the sentences in video time to check.
- **Jump zoom.** Cut to the next sentence tighter: a new piece with a static transform. Alternate wide and tight
  every 2–3 sentences, never on two cuts in a row:
  ```css
  #b { transform: scale(1.12); transform-origin: 50% 38%; }
  ```
- **Slow push.** `at()` animates a `<video>` like any element (checked in the render): transform and filter.
  ```js
  at("#h", [{ transform: "scale(1)" }, { transform: "scale(1.06)" }], 0, 2400, "linear");
  ```
  Offsets on a piece count from the piece's own `data-start`. Never both a CSS transform and an animated one.
- **Cutaway (b-roll).** Over the speaker, a muted piece on track 1 for 1–5 s while their voice goes on under it.
  Cut in on the noun it shows, out before the next sentence:
  ```html
  <video id="cut1" src="uploads/broll.mp4" muted data-start="10.33" data-media-start="3" data-duration="1.5" data-track-index="1"></video>
  ```
  with `#cut1 { z-index: 2; }`. A stock clip comes from `footage {stock: "a few words", orientation: "portrait"}`.
- **Montage on the music.** The `music` reply gives each track's beat (B) and good places to start on it; start
  the music there with data-start 0 and a beat falls at 0 and every B after. Cut every 2 beats for energy, 4 for
  calm, all pieces `muted`, the music not ducked. 100 bpm → B = 0.6 s → a cut every 1.2 s:
  ```html
  <video id="m1" src="uploads/broll.mp4" muted data-start="2.4" data-media-start="0.3" data-duration="1.2" data-track-index="0"></video>
  <video id="m2" src="uploads/broll.mp4" muted data-start="3.6" data-media-start="2.3" data-duration="1.2" data-track-index="0"></video>
  ```
  Land the best shot on a bar line (every 4 beats; the sound map lists both). The sound map's `cut_off_beat` names
  a piece that starts off the beat. A track with no steady beat: hold shots 3–4 s. When someone speaks, the
  words set the cuts, not the beat.
- **Between pieces** a hard cut is the default. A fade only for time passing or a change of place: start the
  incoming piece up to 2 s early on the other track with `data-transition="fade"`. No GPU transition on footage.
- `data-reframe` only on a person on camera: on any other clip the check warns `reframe_no_face`; frame it with
  `object-position` ("30% 50%" keeps the left third).

## 3. A wide clip in a vertical reel (1080 × 1920)

Change the layout only on a cut: a new piece with another id and box. A boxed piece takes `inset: auto` and
its own box; everything else stays the global `video { position: absolute; inset: 0; width: 100%; height: 100%;
object-fit: cover; }`.

| layout | the `<video>` | the rest | for |
|---|---|---|---|
| **Full-bleed** | `data-reframe`, the global rule | captions and callouts over it | one speaker whose face can be followed |
| **Box + title band** | `left: 0; top: 300px; width: 1080px; height: 608px` | kicker + headline from y 960 | the whole wide frame matters: two people, a product |
| **Split** | `left: 0; top: 960px; width: 1080px; height: 960px` + `data-reframe` | a solid panel over the top half with a number or claim | a fact beside the speaker |
| **Picture in picture** | `left: 568px; top: 240px; width: 440px; height: 248px; border-radius: 28px; z-index: 20` | a full-frame graphic scene (z-index 10) | the content leads, the speaker supports |

```css
#b { inset: auto; left: 0; top: 300px; width: 1080px; height: 608px; }
#d { inset: auto; left: 568px; top: 240px; width: 440px; height: 248px; border-radius: 28px; z-index: 20; box-shadow: 0 24px 60px rgba(0,0,0,.55); }
```
A PiP pops in with `at("#d", [{ opacity: 0, transform: "scale(.6)" }, { opacity: 1, transform: "none" }], 0, 500, "cubic-bezier(0.16, 1, 0.3, 1)")`.
A clip shot upright keeps its shape: full-bleed, or a PiP box of the same 9:16 shape.

**The safe band (vertical):** every word, caption and graphic between y 220 and y 1440, the right 140 px
clear. Below y 1440 the apps draw their own caption and buttons: only picture there. Wide videos: 6% margins.

## 4. Dressing a talking head

The face wins: nothing covers it, one graphic at a time, each timed to the word that says it. In a vertical
close-up the face sits about y 400–1000: look at the sheet and keep graphics above or below it.

- **Lower third** at the person's first appearance, once: `motion {name, piece: "lower-third", start: 0.3,
  vars: {name, role, accent, duration: 2–3}}`. It lands just above two lines of captions, clear of the right
  140 px; check on the sheet that it does not cover the chin, and move it with `edit` only if it does.
- **Keyword chip** (a place, a product, a name): a pill in the top band, 0.15 s before the word, held about
  1.5 s, leaving faster than it came. A Lottie accent can sit inside it:
  ```html
  <div id="k1" class="clip" data-start="8.8" data-duration="1.6" data-track-index="2">
    <div id="chip1" class="chip" dir="rtl"><div id="pin1" class="lottie" data-lottie="lottie:accent-pin" data-color="#14110f"></div>الرياض</div>
  </div>
  ```
  ```css
  #k1 { z-index: 20; }
  .chip { position: absolute; right: 140px; top: 240px; display: flex; align-items: center; gap: 8px; padding: 8px 40px 8px 18px; border-radius: 999px; background: #ffb547; color: #14110f; font: 800 72px/1.5 "Cairo", sans-serif; }
  .chip .lottie { position: relative; width: 110px; height: 110px; }
  ```
  ```js
  at("#chip1", [{ opacity: 0, transform: "translateX(80px)" }, { opacity: 1, transform: "none" }], 0, 450, "cubic-bezier(0.16, 1, 0.3, 1)");
  at("#chip1", [{ opacity: 0 }], -300, 250, "cubic-bezier(0.7, 0, 0.84, 0)");   // the exit: end keyframe only
  ```
- **Punch line**: the 2–3 words that carry a sentence, big, in word blocks above the captions, each on its own
  spoken time, the key word in the accent. Blocks keep 3:1 contrast over any footage (bare text over bright
  footage fails it):
  ```html
  <div id="k2" class="clip" data-start="11.85" data-duration="1.9" data-track-index="3">
    <div id="punch" class="punch" dir="rtl"><span id="p1">في</span> <span id="p2">كل</span> <span id="p3" class="hot">مدينة</span></div>
  </div>
  ```
  ```css
  .punch { position: absolute; left: 60px; right: 140px; top: 960px; text-align: center; white-space: nowrap; font: 900 112px/1.5 "Cairo", sans-serif; }
  .punch span { display: inline-block; padding: 0 26px; border-radius: 18px; background: #14110f; }
  .punch .hot { background: #ffb547; color: #14110f; }
  ```
  ```js
  at("#p1", [{ opacity: 0, transform: "translateY(60px)" }, { opacity: 1, transform: "none" }], 0, 400, "cubic-bezier(0.16, 1, 0.3, 1)");
  at("#p2", [{ opacity: 0, transform: "translateY(60px)" }, { opacity: 1, transform: "none" }], 160, 400, "cubic-bezier(0.16, 1, 0.3, 1)");
  at("#p3", [{ opacity: 0, transform: "scale(1.4)" }, { opacity: 1, transform: "none" }], 360, 500, "cubic-bezier(0.34, 1.56, 0.64, 1)");
  ```
  A punch line may run past its piece into the end card above it (a higher track): the words carry the cut.
- **Accents** (`lottie {query}`: underline, circle, arrow, check): on a plain word, not on a block of the same
  colour. A Lottie's stroke sits in the middle of its box: place the box so its middle is just under the word,
  and never on the caption rail (the captions hide it).
- **A number said aloud**: count up to it so it lands as the number is heard (the counter in the
  instructions), in the split panel or a chip.
- **Quote card**: the strongest line as a full-frame graphic with the speaker in a PiP saying it.
- **How often**: under a minute, one graphic every 6–8 s; up to 3 min, every 8–12 s. A graphic held past 8 s
  needs a second beat. Most of the words live in the captions; a punch line is earned, once every 15–20 s.

## 5. Captions — the rail

```html
<div id="cap1" class="cap" data-captions="h" data-cap-style="word" dir="rtl"></div>
<div id="cap2" class="cap" data-captions="a b" data-cap-style="word" dir="rtl"></div>
```
```css
.cap { position: absolute; z-index: 35; left: 60px; right: 140px; bottom: 500px; text-align: center; font: 700 60px/1.6 "Cairo", sans-serif; color: #fff; --cap-active: #ffb547; }
.cap-line { background: rgba(10, 8, 6, .66); padding: 4px 24px; border-radius: 18px; box-decoration-break: clone; -webkit-box-decoration-break: clone; }
```
- **One box per stretch of speech.** A box over pieces with a music-only stretch between them builds a line
  across the gap: it hangs over the montage with words from both sides. Split the ids at every silent stretch.
- The `.cap-line` backing is sized to the words: readable over any shot, never a full-width bar or a grade.
- `word` lights each word as it is said (reels, energy); `phrase` for interviews and calm talk. One family,
  two weights, one accent. The accent on a dark backing is light (amber, yellow, mint): a mid orange-red fails 3:1.
- Sizes: 60–72 px on a reel, 44–56 px on a wide video 80–120 px from the bottom. Never italic for emphasis.
- **Arabic**: `dir="rtl"` on the box, an Arabic family (Cairo, IBM Plex Sans Arabic, Tajawal, Almarai),
  line-height 1.5 or more.
- **Another language**: `subtitles {name}`, translate each sentence short and natural, `subtitles {name, to,
  lines}`, then a second box. For a Gulf audience the Arabic line is the rail and the original sits above it,
  smaller:
  ```html
  <div id="cap" class="cap" data-captions="s" data-cap-style="word"></div>
  <div id="cap-ar" class="cap" data-captions="s" data-cap-lang="ar" data-cap-style="phrase" dir="rtl"></div>
  ```
  ```css
  #cap { bottom: 700px; font-size: 46px; }
  #cap-ar { bottom: 500px; font: 700 60px/1.6 "IBM Plex Sans Arabic", sans-serif; }
  ```
- Never type captions by hand: the service fills the box from the words.

## 6. Sound

- The speaker's voice is the clock and the loudest thing. Music only when the person wants it, under the
  speech with `data-duck` naming every speech piece: it dips under each sentence, rises in a montage and on the
  end card, and fades out by itself.
  ```html
  <audio id="bed" src="music:andrewkn-listen" data-start="0" data-media-start="21" data-duck="h a b"></audio>
  ```
- Start the music at one of the `music` reply's good places, not its quiet intro. Talk: calm or warm
  tracks; a recap montage: an upbeat one with a bpm.
- Cutaways and montage pieces are `muted`; a cutaway over a speaker keeps the speaker's piece (and voice)
  playing under it.
- Sound effects stay out of the speech: a `pop` on a chip at `data-volume="0.4"`, a `whoosh` into a montage or
  the end card, an `impact-bass-1` on the punch line's last word in a gap (`motion-design` §10).

## 7. Shapes that work

| kind | length | beats |
|---|---|---|
| **Testimonial** | 20–40 s | hook quote 3–5 s → who (lower third) → the problem → what changed → the result with a number (count-up) → end card |
| **Founder / brand story** | 20–45 s | hook line → a montage on the beat with a chapter title → origin (place and date chips) → growth (a number) → the mission as a punch line → end card |
| **Event recap** | 15–30 s | title with date and place → 6–12 shots on the beat (2 beats each) → one sound bite in the middle (music ducked) → closing title + logo |
| **Podcast clip** | 20–45 s | one strong exchange; box + title band with both names; word captions |
| **Interview with b-roll** | 30–60 s | the voice carries; a cutaway on every noun worth showing, never more than half the time |

## 8. The end card, sizes, the last look

- **End card**: a scene after the last piece with its own background, 2–3 s: the brand or logo, one line, one
  handle or ask. The root's `data-duration` = the last piece's end + the card. Nothing to read below y 1440.
- **Several sizes**: `data-sizes="vertical square"` on the root; a `data-reframe` piece follows at every size, a
  boxed piece and the graphics around it need a rule for each other size
  (`#root[data-shape="square"] #b { top: 60px; height: 608px; }`). `look {name, size}` each one: a PiP clear of
  the headline in vertical covered it in square.
- **Before render**: the face clear in every frame; captions readable over every shot; each callout on its
  word (check the "Spoken:" times); no caption line across a silent stretch; nothing in the bottom 480 px or the
  right 140 px; the lower third off the caption rail; the end card reached.
