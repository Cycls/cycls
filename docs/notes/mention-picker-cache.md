# The @-mention picker's dead-query cache

Why the composer's `@` file picker can hide a file that exists, why the web has
never appeared to suffer from it, and the two-line fix.

**Status**: fixed in the mobile client (`cycls-mobile-app@ab5fca4`), open in
`client/src/components/input-box.tsx`.

## The mechanism

When you type `@budget` and the search returns **nothing**, the picker records
the query it died on:

```ts
// input-box.tsx:128
if (!r.length && mention.query.trim()) setDead({ start: mention.start, query: mention.query });
```

Anything that extends that query is then swallowed without a request:

```ts
// input-box.tsx:24
export const mentionSuppressed = (mention, dead) =>
  !!(mention && dead && mention.start === dead.start && mention.query.startsWith(dead.query));
```

This is deliberate and worth keeping. Typing a sentence that happens to contain
an `@` costs one request rather than one per keystroke, and backspacing to a
shorter query that *did* have hits revives the picker.

## The bug

Nothing ever clears `dead`. The three writes are:

| line | what |
|---|---|
| 128 | latch on an empty result |
| 140 | clear on picking a file |
| 166 | shut the session on Esc (`query: ""`) |

There is no clear on submit, and none when a turn writes files. So the note
outlives the thing that justified it: once `@budget` has found nothing, it keeps
finding nothing for the life of the component — including after the agent
creates `budget.csv`.

The tell is that a bare `@` lists the file perfectly well, while the word that
names it returns nothing.

## Why the web looks fine

`dead` is React state, so **a page reload wipes it**. A browser tab gets
reloaded constantly, and the sequence needs three things to line up:

1. a query returning **zero** results, not merely few
2. that file **later existing**
3. the same word retyped with the `@` at the **same index**

Everyday use — type `@`, look at the list, pick one — never touches it, because
the note only exists for words that found nothing.

The mobile client runs the same code but stays mounted for days, so the note
survives long enough to be hit in ordinary use. Same defect, very different
exposure. "Works perfectly on web" and "the bug is real" are both true.

### Reproducing it on web

Do not reload the page at any point:

1. Type `@zzztest` — empty, correctly
2. Leaving the page open, have the agent create `zzztest.txt`
3. Clear the box and type `@zzztest` again, with `@` as the first character both times
4. The picker stays empty — now type just `@` and `zzztest.txt` is in the list

## The fix

The note should outlive the keystrokes it was meant to spare, and nothing else.
Sending, emptying the box, and any turn that writes files all invalidate its
premise. `isStreaming` is already a prop, so no new plumbing:

```ts
// A dead query is only allowed to outlive the keystrokes it was meant to spare.
const mentionCacheKey = `${input.length === 0 ? 1 : 0}:${isStreaming ? 1 : 0}`;
useEffect(() => { setDead(null); }, [mentionCacheKey]);
```

`isStreaming` is the web's signal that files may have changed — the same reason
`useRefreshOnTurnEnd` (`hooks/use-files.ts:170`) re-lists when streaming stops.
The mobile client keys off its files epoch, which is the same event.

This does not touch the happy path: within a session the suppression still
spares a request per keystroke.

## The deeper point

`mentionAt` was **byte-identical** between `input-box.tsx` and the mobile
`Composer.tsx`, comments included, and `mentionSuppressed` was the same
expression inlined. Two hand-copied versions of pure logic, neither tested, is
exactly the situation `src/core/` exists to prevent — cf. `stream.mjs` and
`apps.mjs`, both of which say so in their headers.

Mobile has since moved both into `src/core/mentions.mjs` with tests. If the web
copy is left as a third transcription, this will drift again. Worth extracting
on that side too.
