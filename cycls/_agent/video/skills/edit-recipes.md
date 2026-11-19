---
name: edit-recipes
description: Methods for cutting the person's footage (shorts from a long talk, script edits, clip reels, captions, two languages, multicam, graphics, storyboards), then checks for a flat cut.
---

# edit-recipes: methods for an edit, and direction checks

Load it with `footage-video` (which it never repeats) when the job is an edit: a long recording, a folder of clips,
a script and its takes, a reference to follow. Each method says when, the steps in Cycls terms, and what to check.
Everything rests on the `footage` reply: the shots and where they change, the sheet, every sentence and word with
its time, each clip's best and weak stretches. A piece is a `<video>` at the root with `data-start`,
`data-media-start` and `data-duration`; a word is heard at `data-start + (word time − data-media-start)`.

## 1. Shortlist shorts

When: clips, highlights or shorts from one long podcast, interview, course or live session.
- `footage {path}` (call again to collect a long one); fix misheard names in `uploads/<clip>.words.json` first.
- Before cutting anything, reply with a shortlist, best first. For each: start and end (from sentence times), its
  hook line quoted, and what it has, counted rather than scored: a hook in its first 3 s · stands alone (no "as I
  said") · a payoff · a number, an example or a contrast · its risks (needs earlier context, names a private person,
  unclear sound). About one candidate per 5–10 min of source, at least four when the talk has them; when it has
  fewer strong moments, say so. The person picks.
- Build one first: 20–75 s (90 at most), opening on its hook sentence. Ask for a go on its style, then make the
  others the same way, one video each.
- Vertical: one speaker full-bleed with `data-reframe`; two speakers, box + title band; a screen recording boxed with
  `data-grade="none"` on track 1, over a `muted` copy of the same piece on track 0 (same times) filling the frame with
  `filter: blur(40px)`.
- Captions: `word` over the hook's stretch, `phrase` after it (two boxes, split at a pause).
Check: each short makes sense without the source; its first line is the hook; the crop never loses the speaker.

## 2. Edit to a script

When: the person has a script and several recorded takes.
- `footage` every take. Map each script line to the takes that say it (match the sentences); pick the best take of
  each line (clean start, no stumble, the energy the line needs), not the last one.
- A line no take holds is reported missing, never written on screen as if said; a take that matches only in part is
  used and named in the reply. Never two speakers in one line, never reordered inside a sentence.
- One piece a line, in script order, cut 0.15 s before its first word and 0.25 s after its last.
- Captions name every piece id; music, if any, `data-duck`s under all of them.
Check: reply with the map (line → take and times) and each unused take with its reason.

## 3. Clips to a reel

When: a folder of short clips (a trip, an event, a shoot, a week) into one 15–30 s vertical reel.
- `footage` each clip and read every sheet: each clip kept or skipped with a reason (shaky, a duplicate, dark, no
  subject). Never use them all; no shot twice.
- Order the keeps as a small arc: opener, detail, wide, people, closer.
- `music {query, length}` first; cut every 2 beats, faster in the middle, a longer last shot landing on a bar line;
  pieces `muted`, each in its best stretch; on every other piece a push-out (`scale(1.07)` → `scale(1)` over the
  piece, DRIFT).
- A wide clip: `data-reframe` only on a person; anything else framed with `object-position`. Never squashed, never
  letterboxed.
- The title on the first beat (an on-footage scene, its hl there at 0 s), gone by 3 s. Speech kept in the reel keeps
  its sound, and the music ducks under it.
Check: no `cut_off_beat` in the sound map; every subject in frame after the crop; the length asked for.

## 4. Caption looks

When: a talking video needs captions, or a new caption look.
You control the box's place and size, `.cap-line`, `.cap-word`, `--cap-active` and `--cap-active-bg` (on the box's
id), and `data-cap-style` (`word` or `phrase`). Three looks:

| look | how | for |
|---|---|---|
| clean | `phrase`; sentence case on the dark `.cap-line` pill; no accent | interviews, brand films, talk over 20 s |
| pop | `word`; the look's display face at 72 px on a reel; `--cap-active: #FFE14D` | hooks, reels of 20 s or less |
| marker | `word`; `--cap-active-bg` a solid accent behind the said word, light text | creator tips of 20 s or less |

- One look a video, one emphasis colour. A word to stress beyond the one being said is a punch line or a `note`,
  never the captions' job. Capitals only on Latin.
- When the person wants to choose: build one, `look` at a spoken moment, and name the other two in one line;
  never render three versions.
Check: the words match the sound; nothing over the face or in the platform zones; one look throughout.

## 5. Captions in two languages

When: the original words and a translation on screen together.
- Ask the target language unless the brief says it (never guess it from the chat). `subtitles {name}`; translate each
  sentence short and natural, keeping the names and terms the person keeps; `subtitles {name, to, lines}`.
- Two boxes on the same piece ids: the original, and the translation with `data-cap-lang` in `phrase` (a translation
  has no word times).
- The language the audience reads first is the larger line on the rail; the other sits above it at about 70% of
  its size, the same width (for a Gulf audience the Arabic line is the rail). An Arabic box `dir="rtl"`, line-height
  1.5, an Arabic family on its id.
- Split both boxes at every pause over 1 s (one box per stretch of speech): no pair hangs over a silence.
Check: each pair readable twice while it is said; the translation says no more than was said; `look` at an Arabic
frame for missing letters.

## 6. Storyboard to motion

When: the person approved still frames (images, or a Design deck exported as JPEG) and wants them moving.
- One document, one scene per frame, in order; scene lengths from the plan or the music's beats.
- Rebuild each frame as live markup: its words in roles, its screenshots as `<img>`. The frame image is your
  reference, never the scene (its words would be baked in and could not be edited).
- Each scene enters in 0.4–0.8 s, holds the exact frame ≥1.2 s, and hands on in 0.3–0.5 s. Layers in reading order
  (ground, headline, proof, labels, accent), 80–120 ms apart; one easing family for the film (LAND in, LEAVE out).
- Hand each scene to the next with a move that carries over the cut (`motion-design` §8): no blank frame, no scene
  fading to nothing. No idle drift, bounce or rotation without a job.
Check: `look` at each hold and compare it with its frame (layout, copy, crop); `look` 0.2 s each side of every seam.

## 7. Shot breakdown

When: the person gives a video to say "make one like this" (their own upload), or wants a shoot briefed from it.
- `footage {path, as: "reference", brief}` reads it shot by shot: what is on screen, its words, layout and motion,
  the hook, the pace, the closest look.
- Reply with a table, one row a shot: time, shot size (wide, medium, close, detail), movement (still, push, pan,
  handheld; an estimate marked as one), why it cuts there, what it adds. Over 20 shots: give the count and ask which
  stretch.
- End with one or two sentences the person can shoot or cut to ("close-ups only on the product; a cut every second
  beat").
- Rebuild that structure with their brand, words, pictures and music; never the reference or a frame of it.

## 8. An ad script

When: a promo or creator-style ad needs its script before anything is made.
- Offer 2–3 angles in one line each (the pain, the change, the demo, the objection) unless the brief settles it;
  write the chosen one in full.
- A table: time · beat · line · picture. The hook in the first 1.5 s (a concrete result or a true, surprising line);
  then the problem, the proof SHOWN (a demo, a before and after, a real screen), the payoff, and one call to action in
  the last 2–3 s. A beat every 2–5 s.
- Read it at 2.5 words a second (Arabic 2): it fits the length, or it is cut.
- Every claim from the person's page or notes: no invented price, number, guarantee or review; no competitor named;
  every picture one the tools can make (their footage, stock, a look's scene, a piece).
- Then `voice` (or their footage) and build with `promo-reel`.

## 9. Graphics on a talking video

When: placing graphics on a talking head, a lecture, a tutorial, a podcast.
- Plan before building, one line each: trigger word · its time in the video · type · place. Nothing on a timer,
  nothing on a filler.
- The line chooses the type: a number → a `num` in the split panel, or `note` impact · steps → numbered chips or a
  short list · a choice → the two sides of a split card · an opinion or a quote → `note` (highlighter, red-pen) or
  quote + by · a name → `lower-third` · a spec → `note` spec · the call to action → the end card.
- Each lands on its word, enters in 300–400 ms, stays 0.3–0.6 s after its last word and is gone before the next
  trigger. How often: `footage-video` §5. Never the same type twice running unless it is a series; 1.5 s clear after
  a full-frame graphic.
- Opposite the face, above the caption rail; never over hands or the product being shown.
Check: `look` at every trigger time for overlap; nothing appears before its line is said.

## 10. Recreate a reference edit

When: the person has their own talking-head footage and a reference edit (their upload) whose style they want.
- `footage` their clips, and `footage {path, as: "reference"}` on the reference. List its beats: every cut, zoom,
  card, name tag and cutaway, with its time and its job.
- Give each beat to the person's line that does the same job (a key line, a number, a list, the call to action):
  function, not timestamp; skip a beat where nothing they said fits.
- Average piece length within ±20% of the reference's. Its punch-ins are `footage-video`'s jump zoom (a cut to a
  piece at 1.1–1.2×, the origin above the eyes) on the key word; cards held 1–1.5 s; captions as in method 4.
- Never the reference's words, music, logos or footage.
Check: reply with the beat list, each beat matched, adapted or skipped, with its reason.

## 11. Live-sale clips

When: a recorded live-shopping session becomes one vertical clip per product.
- `footage` the replay; find each product's stretch from the sentences and the sheet; skip a product whose pitch was
  cut off; cut greetings, giveaways, stock counts and queue numbers.
- Frame 0: the host and this product's strongest line, word for word, as the hook (hl set to none, top band);
  `data-reframe` on the host, the product beside the face.
- A product tag (its name and one plain fact) when the host names it; the offer as the talk turns from proof to the
  deal; the end card's line the one call to action, held still.
- Prices exactly as said and as the person's price policy allows; no "today only" or countdown in a clip posted
  later; no miracle, cure or best-ever claim.
Check: each clip stands alone; the hook is a real quote; one product a clip.

## 12. Multicam

When: one session filmed on two or more cameras (a podcast, an interview, a panel).
- `footage` every angle. The same sentence at the same moment in two replies is one moment seen twice: its first
  word's time in each gives the offset (B's time − A's time). Take it from a sentence near the start, the middle and
  the end: the three agree within 0.04 s, or say the angle drifts and do not stretch it.
- The angle with the clearest sound is the spine: its pieces on track 0 carry the sound and the timing. Each other
  angle is a `muted` piece on track 1 over it (z-index above), its `data-media-start` = the spine's media time at that
  moment + the offset.
- Show whoever speaks: cut 0.15–0.25 s after a new speaker starts, or on their breath; shots ≥1.5 s; the wide when two
  voices overlap for more than 0.8 s; a reaction 0.5–1 s, only on a visible response, at most two a minute, never on
  the punch line; on a long turn, the wide every 20–40 s. Never a cut on every word.
- Captions on the spine's ids.
Check: the mouth on each angle matches the words at its start and end (`look`); every cut follows the voice; any
doubtful offset named in the reply.

## Direction checks

For a cut that feels like slides, flat or generic; what `video-direction` and `motion-design` do not already say.

**"Feels like slides": find the level, top first, and stop where it is.**
1. Expression: a list of claims standing still? Carry the main one by something that happens: an action, a relation
   changing, the type's rhythm, an edit.
2. Structure: every scene full layout → same entrance → hold → clear? Keep a repeat only when the content is a series.
3. Attention: does each cut make the eye search for the subject again? Continue what continues; break clearly
   where the story turns.
4. Time: moves too long, reading too short, or no contrast between scenes. Never speed everything up.
5. Detail, only now: paths, eases, delays, sound, a second move.
A push on a screenshot is a move, not a beat: it counts when it reveals a readable new detail or a relation.

| you see | check | change |
|---|---|---|
| every scene the same page, new words | layout, main move, timing all repeat | rechoose the framing or the unit (one number, one action) |
| much moves, little is understood | what the eye should be on, at 1× | cut competing moves; keep one still anchor |
| it drags | time the moving, the reading, the empty wait apart | cut the wait, keep the reading |
| the change is lost under a camera move | its size on screen while it happens | let it happen at a readable size, then reframe |
| a read line is cut by something leaving | the exit's path | clear the path, or move the words first |
| a seam jumps | both sides, frame by frame | same place and size for a carried object; same speed for a matched move |
| a template feel | bounce, float, slide-up on everything | rewrite the moves from the object and the brand |
| busy, no proof | which frames show the real thing working | add the real demo, or narrow the claim |

**Weak, and better, motion phrases.**
- A line about flexibility. Weak: the words slide in together and hold while a circle drifts; or the spacing
  shrinks, then grows, in equal time and ease. Better: it reads at once; on the stressed word the space snaps tight,
  the main word first, the rest 100–150 ms after; on the release it opens in the reading direction and lands. Arabic:
  move whole words, or hard-cut from a tight crop to a wide one.
- A product with a mechanism (a folding lamp). Weak: its photo flies in on a card, a title, it flies out: the
  container moved, not the product. Better: open close on the hinge; the arm opens from its pivot at the material's
  speed, its shadow answering; widen at the turn; then its light takes over. With stills of a few real states only,
  hard-cut between them with the pivot in one place rather than fake the in-between.
- A process (orders given to drivers). Weak: a title and the final screen zooming slowly; or every item enters,
  waits, moves, waits. Better: a few items and the open slots; the current item lit, its slot answering, the count
  updating; later items faster on the grammar learned; the result held.

**Before render**: take the product's name out; could this motion sell anything? Are a click, a carried object or a
climax invented to fill a slot? Undo a change made only to differ from the last video.
