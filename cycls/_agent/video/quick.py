"""A small edit, and the moments it shows.

After an `edit` the full check — the browser check and a sheet of nine frames — took about 16 s on
the GPU for a three-clip footage video; frames alone of one or three moments took 8 to 10 s (dev,
2026-11-08), and an edit's whole call in the app about 26 s. Most edits after the first draft are
small: a word, a colour, a size. An edit that changes only the words and the inline styles of
elements that were already there — the same elements in the same places, the same attributes, the
same script and <style> — is checked by lint and a frame of each scene it touched, up to three. The
browser check then runs beside the render (`run._render`), so nothing reaches the MP4 unchecked.

From 2026-11-09 a small edit is also one that swaps a clip or a photo (src, data-media-start and the media's
own attributes), changes a class, moves or trims a scene (data-start, data-duration: every scene whose time
moved is looked at), changes the numbers of an at() call on an element by its #id, or changes a <style>
rule whose selector names its elements plainly (tags, .classes, #ids). In a real turn on production
(2026-11-09) both edits after the first draft were of these kinds — a clip swapped with its push, end-card
type sized up — and each paid the full check, 23-25 s.
"""
import re
from html.parser import HTMLParser

MOST = 3                     # scenes one small edit may touch; more is a big edit
AT = 0.6                     # how far into its scene a frame is taken: in, and settled
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
_LOCAL = {"src", "poster", "alt", "class", "data-media-start", "data-volume", "data-grade", "data-reframe",
          "data-anim", "data-anim-delay", "data-track-index"}     # an element's own: its scene alone sees them
_TIMING = {"data-start", "data-duration"}
_AT = re.compile(r"""^at\s*\(\s*(["'`])#([\w-]+)\1\s*,""")
_SIMPLE = re.compile(r"^(?:[a-zA-Z][\w-]*)?(?:[.#][\w-]+)*$")
_PSEUDO = re.compile(r"::?[\w-]+(?:\([^)]*\))?")
_REF = re.compile(r"^\s*([A-Za-z_][\w-]*)\s*(?:([+-])\s*(\d+(?:\.\d+)?))?\s*$")


class _Shape(HTMLParser):
    """The elements in order: tag, parent, inline style, own text, attributes."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags, self.parents, self.styles, self.texts, self.attrs = [], [], [], [], []
        self._open = []

    def handle_starttag(self, tag, attrs):
        i = len(self.tags)
        a = {k: v or "" for k, v in attrs}
        self.tags.append(tag)
        self.parents.append(self._open[-1] if self._open else None)
        self.styles.append(a.get("style", ""))
        self.texts.append("")
        self.attrs.append(a)
        if tag not in _VOID:
            self._open.append(i)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self._open.pop()

    def handle_endtag(self, tag):
        for k in range(len(self._open) - 1, -1, -1):
            if self.tags[self._open[k]] == tag:
                del self._open[k:]
                return

    def handle_data(self, data):
        if self._open:
            self.texts[self._open[-1]] += data


def _shape(html):
    try:
        s = _Shape()
        s.feed(html)
        s.close()
        return s
    except Exception:  # noqa: BLE001 - what the parser cannot read is no small edit
        return None


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and x >= 0 else None


def _window(s, i, root, depth=0):
    """[start, end) of the timed element `i` on the video's clock; a start may name another element
    ("s1", "s2 + 0.5": when that one ends). None when it cannot be told."""
    a = s.attrs[i]
    length = _num(a.get("data-duration"))
    start = _num(a.get("data-start"))
    if start is None and depth < 8:
        m = _REF.match(a.get("data-start", ""))
        ref = next((k for k, x in enumerate(s.attrs) if m and x.get("id") == m.group(1)), None)
        if ref is not None and s.parents[ref] == root:
            w = _window(s, ref, root, depth + 1)
            if w:
                off = float(m.group(3) or 0)
                start = w[1] + (off if m.group(2) != "-" else -off)
    if start is None or not length:
        return None
    return start, start + length


def _split(code):
    """A script's top-level statements, split at `;` and new lines outside strings, comments and brackets,
    comments dropped and white space made single."""
    out, cur, depth, i, n = [], [], 0, 0, len(code)
    while i < n:
        c = code[i]
        if code.startswith("/*", i):
            j = code.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if code.startswith("//", i):
            j = code.find("\n", i)
            i = n if j < 0 else j
            continue
        if c in "\"'`":
            j = i + 1
            while j < n and code[j] != c:
                j += 2 if code[j] == "\\" else 1
            cur.append(code[i:j + 1])
            i = j + 1
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        if depth == 0 and c in ";\n":
            out.append(" ".join("".join(cur).split()))
            cur = []
        else:
            cur.append(c)
        i += 1
    out.append(" ".join("".join(cur).split()))
    return [x for x in out if x]


def _script_ids(before, after):
    """The #ids whose at() calls alone changed between two scripts, or None: anything else changed."""
    a, b = _split(before), _split(after)
    if len(a) != len(b):
        return None
    ids = set()
    for x, y in zip(a, b):
        if x == y:
            continue
        mx, my = _AT.match(x), _AT.match(y)
        if not mx or not my or mx.group(2) != my.group(2):
            return None
        ids.add(mx.group(2))
    return ids


def _rules(css):
    """{selector: [bodies]} of a style sheet, or None when it cannot be read."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out, depth, i, mark, n, sel = {}, 0, 0, 0, len(css), ""
    while i < n:
        c = css[i]
        if c in "\"'":
            j = css.find(c, i + 1)
            i = n if j < 0 else j + 1
            continue
        if c == "{":
            if depth == 0:
                sel, mark = " ".join(css[mark:i].split()), i + 1
            depth += 1
        elif c == "}":
            depth -= 1
            if depth < 0:
                return None
            if depth == 0:
                out.setdefault(sel, []).append(" ".join(css[mark:i].split()))
                mark = i + 1
        i += 1
    return out if depth == 0 else None


def _css_subjects(before, after):
    """The plain selectors (a tag, .classes, an #id) of the elements whose rules alone changed, or None: an
    at-rule, an attribute selector, a * or :root changed, or a sheet cannot be read."""
    a, b = _rules(before), _rules(after)
    if a is None or b is None:
        return None
    out = []
    for sel in sorted(set(a) | set(b)):
        if a.get(sel) == b.get(sel):
            continue
        if sel.startswith("@") or not sel:
            return None
        for part in sel.split(","):
            last = re.split(r"\s*[>+~]\s*|\s+", part.strip())[-1]
            if ":root" in last:
                return None
            last = _PSEUDO.sub("", last)
            if not last or not _SIMPLE.match(last):
                return None
            out.append(last)
    return out


def _matches(attrs, tag, simple):
    m = re.match(r"^([a-zA-Z][\w-]*)?((?:[.#][\w-]+)*)$", simple)
    if m.group(1) and m.group(1).lower() != tag:
        return False
    classes = set((attrs.get("class") or "").split())
    for kind, name in re.findall(r"([.#])([\w-]+)", m.group(2)):
        if (kind == "#" and attrs.get("id") != name) or (kind == "." and name not in classes):
            return False
    return True


def moments(before, after):
    """The times to look at when `before` → `after` is a small edit (see above), else None."""
    a, b = _shape(before), _shape(after)
    if a is None or b is None or a.tags != b.tags or a.parents != b.parents:
        return None
    root = next((i for i, x in enumerate(b.attrs) if "data-composition-id" in x), None)
    if root is None or a.attrs[root] != b.attrs[root]:
        return None
    total = _num(b.attrs[root].get("data-duration"))
    touched, timing = set(), False
    for i, tag in enumerate(a.tags):
        was = {k: v for k, v in a.attrs[i].items() if k != "style"}
        now = {k: v for k, v in b.attrs[i].items() if k != "style"}
        changed = {k for k in set(was) | set(now) if was.get(k) != now.get(k)}
        if tag in ("script", "style"):
            if changed:
                return None
            if a.texts[i] == b.texts[i]:
                continue
            if tag == "script":
                ids = _script_ids(a.texts[i], b.texts[i])
                if ids is None:
                    return None
                for name in ids:
                    k = next((j for j, x in enumerate(b.attrs) if x.get("id") == name), None)
                    if k is None:
                        return None
                    touched.add(k)
            else:
                subjects = None if "data-cycls-brand" in b.attrs[i] else _css_subjects(a.texts[i], b.texts[i])
                if subjects is None:
                    return None
                for simple in subjects:
                    for j, x in enumerate(b.attrs):
                        if _matches(x, b.tags[j], simple):
                            if j == root or b.tags[j] in ("html", "head", "body"):
                                return None     # what holds every scene
                            touched.add(j)
            continue
        if changed - _LOCAL - _TIMING:
            return None
        if changed & _TIMING:
            timing = True
        if changed & _LOCAL or a.styles[i] != b.styles[i] or a.texts[i] != b.texts[i]:
            if i == root or tag in ("html", "head", "body", "title"):
                return None
            touched.add(i)
    scenes = []
    for i in sorted(touched):
        top = i                             # the scene it is in: its ancestor at the root
        while top is not None and b.parents[top] != root:
            top = b.parents[top]
            if top is not None and "data-composition-id" in b.attrs[top]:
                return None                 # inside a composition of its own: its own clock
        if top is None:
            return None
        if top not in scenes:
            scenes.append(top)
    if timing:                              # every scene whose time moved, looked at where it is now
        for k, p in enumerate(b.parents):
            if p == root and k not in scenes and _window(a, k, root) != _window(b, k, root):
                scenes.append(k)
    if not scenes or len(scenes) > MOST:
        return None
    times = []
    for top in scenes:
        w = _window(b, top, root)
        if not w:
            return None
        t = w[0] + (w[1] - w[0]) * AT
        if total:
            t = min(t, total - 0.05)
        times.append(round(max(0.0, t), 2))
    return sorted(set(times))
