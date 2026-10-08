"""A PDF taken apart for a design (the tool's `extract` action): its text and tables by
page, its pictures, and a page or a figure drawn for the model to look at or reuse."""
import asyncio, base64, json, pathlib, re
from ..paths import _resolve_path
from .images import _DESIGN_IMAGE_MAX, _DESIGN_QA_MAX, _image_size


async def _run_tool(*argv, timeout=60):
    """A command-line tool run to its end → (exit code, stdout)."""
    proc = await asyncio.create_subprocess_exec(*argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise
    return proc.returncode, out


_PDF_TEXT_PAGE = 5000       # characters of one page's text handed to the model
_PDF_TEXT_ALL = 16000       # …and of one reply: with what follows it, under the 20,000 at which a reply is filed (spill.SPILL_AT)
_PDF_PICTURES = 30          # pictures kept
_PDF_PICTURE_MIN = 200      # px on its shorter side: smaller is an icon or a rule
_PDF_TABLE_ROWS = 40        # rows of one page's tables shown as they are laid out
_PDF_LOOK_DPI = 100         # a page drawn for the model to look at
_PDF_CUT_DPI = 200          # …and a figure cut out of one, to be used again
# Letters saved as the glyphs they were drawn with: Latin ligatures (ﬁ), and Arabic in its
# presentation forms (ﻟ ﺎ ﻋ) — what a PDF made from Word often holds instead of the letters.
_SHAPED = re.compile("[\ufb00-\ufb06\ufb50-\ufdff\ufe70-\ufeff]+")
_SHAPED_ARABIC = re.compile("[\ufb50-\ufdff\ufe70-\ufeff]")
_DIRECTION_MARKS = re.compile("[\u200e\u200f\u202a-\u202e\u2066-\u2069]")     # what pdftotext wraps right-to-left text in


def _laid_out_tables(page):
    """The rows of a page's tables, from its text as laid out (`pdftotext -layout`): runs of
    lines that are three or more cells apart, two of them figures — each row's cells joined
    by " | ". Reading order keeps a paragraph whole and takes a table apart cell by cell;
    this is the other half."""
    cells = lambda line: [c for c in re.split(r"\s{2,}", line.strip()) if c]
    figure = lambda c: (len(c) <= 16 and bool(re.search(r"\d", c))) or c in ("-", "–", "—")
    lines = page.split("\n")
    row = [len(c) >= 3 and sum(map(figure, c)) >= 2 for c in map(cells, lines)]
    out, i = [], 0
    while i < len(lines):
        if not row[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(lines) and (row[j + 1] or (j + 2 < len(lines) and not lines[j + 1].strip() and row[j + 2])):
            j += 1
        rows = [k for k in range(i, j + 1) if row[k]]
        if len(rows) >= 3:
            head = next((k for k in range(i - 1, max(-1, i - 3), -1) if lines[k].strip()), None)
            if head is not None and len(cells(lines[head])) >= 3:
                rows.insert(0, head)                      # the line over them, when it is their heading
            out += ([""] if out else []) + [" | ".join(cells(lines[k])) for k in rows]
        i = j + 1
    return out[:_PDF_TABLE_ROWS]


async def _pdf_parts(inp, workspace, name):
    """An existing PDF taken apart to be made again as a document: its text, page by
    page, and its pictures saved into designs/<name>-assets/ (poppler: pdftotext,
    pdfimages). The model reads this, then renders a `document` that uses them.

    The words are read in reading order — "as laid out" set a two-column page's columns
    side by side on every line — and a page's tables are added from the laid-out reading,
    which alone keeps a row together. With `page`, one page is drawn to look at, and with
    `area` a figure is cut out of it (`_pdf_page`)."""
    import hashlib, tempfile, unicodedata
    src = inp.get("path") or inp.get("src")
    if not isinstance(src, str) or not src.strip():
        return 'Error: `extract` needs `path` — a PDF in the workspace, e.g. "attachments/report.pdf".'
    try:
        path = _resolve_path(src, workspace.root)
    except ValueError as e:
        return f"Error: {e}"
    if not path.is_file():
        return f"Error: {src} doesn't exist in the workspace."
    if path.suffix.lower() != ".pdf":
        return f"Error: {src} isn't a PDF — `extract` reads a PDF's text and pictures."
    if inp.get("page") is not None:
        return await _pdf_page(inp, workspace, name, path, src)
    # `pages`: reading on — a long PDF's text comes a reply's worth at a time.
    span = None
    if inp.get("pages") is not None:
        v, m = inp["pages"], None
        if isinstance(v, int) and not isinstance(v, bool):
            span = (v, v)
        elif isinstance(v, (list, tuple)) and len(v) in (1, 2) and all(isinstance(n, int) and not isinstance(n, bool) for n in v):
            span = (v[0], v[-1])
        elif isinstance(v, str) and (m := re.fullmatch(r"\s*(\d+)\s*(?:(?:[-–—:]|to)\s*(\d+))?\s*", v)):
            span = (int(m[1]), int(m[2] or m[1]))
        if not span or not 1 <= span[0] <= span[1]:
            return 'Error: `pages` is the pages to read — a number, or a range like "5-8".'
    only = ("-f", str(span[0]), "-l", str(span[1])) if span else ()
    root = pathlib.Path(workspace.root)
    assets_rel = f"designs/{name}-assets"
    letters = lambda t: _SHAPED.sub(lambda m: unicodedata.normalize("NFKC", m[0]), _DIRECTION_MARKS.sub("", t))
    try:
        _, info = await _run_tool("pdfinfo", str(path), timeout=20)
        info = info.decode("utf-8", "replace")
        length = int((re.search(r"^Pages:\s+(\d+)", info, re.M) or [0, 0])[1])
        if span and length and span[0] > length:
            return f"Error: {src} has {length} pages."
        code, text = await _run_tool("pdftotext", *only, "-enc", "UTF-8", str(path), "-", timeout=90)
        if code != 0:
            return f"Error: couldn't read {src} — it may be damaged or locked with a password."
        _, laid = await _run_tool("pdftotext", *only, "-layout", "-enc", "UTF-8", str(path), "-", timeout=90)
        text = text.decode("utf-8", "replace")
        shaped = len(_SHAPED_ARABIC.findall(text))
        pages = [letters(p).strip() for p in text.split("\f")]
        tables = [_laid_out_tables(letters(p)) for p in laid.decode("utf-8", "replace").split("\f")]
        # A scan is pictures of its pages: not pictures to use again.
        paper = re.search(r"^Page\s+(?:\d+\s+)?size:\s+([\d.]+) x ([\d.]+)", info, re.M)
        scan = not any(pages)
        shape = float(paper[1]) / float(paper[2]) if scan and paper and float(paper[2]) else None
        with tempfile.TemporaryDirectory() as tmp:
            if not span:                                  # (reading on: its pictures were taken the first time)
                await _run_tool("pdfimages", "-all", str(path), str(pathlib.Path(tmp) / "img"), timeout=120)
            found = sorted(pathlib.Path(tmp).iterdir())

            def keep():
                seen, kept = set(), []
                for f in found:
                    ext = {".png": "png", ".jpg": "jpg", ".jpeg": "jpg"}.get(f.suffix.lower())
                    if not ext or len(kept) >= _PDF_PICTURES:
                        continue
                    data = f.read_bytes()
                    size, digest = _image_size(data), hashlib.sha1(data).hexdigest()
                    if not size or min(size) < _PDF_PICTURE_MIN or digest in seen or len(data) > _DESIGN_IMAGE_MAX:
                        continue
                    if shape and max(size) >= 900 and abs(size[0] / size[1] - shape) < 0.02 * shape:
                        continue                          # a page of a scan
                    seen.add(digest)
                    (root / assets_rel).mkdir(parents=True, exist_ok=True)
                    rel = f"{assets_rel}/picture-{len(kept) + 1}.{ext}"
                    (root / rel).write_bytes(data)
                    kept.append((rel, size))
                return kept
            pictures = await asyncio.to_thread(keep)
    except FileNotFoundError:
        return "Error: reading a PDF's parts needs poppler (pdftotext, pdfimages) in this agent's image."
    except asyncio.TimeoutError:
        return f"Error: {src} took too long to read — try a smaller PDF."
    field = lambda key: (re.search(rf"^{key}:[ \t]+(\S.*)$", info, re.M) or [None, ""])[1].strip()
    while pages and not pages[-1]:
        pages.pop()
    look = f'extract {{"path": {json.dumps(src, ensure_ascii=False)}, "page": 1}}'
    count = field("Pages") or str(len(pages))
    first = span[0] if span else 1
    end = first + len(pages) - 1
    if span:
        lines = [f"{src} — pages {first}–{end} of {count}." if end > first else f"{src} — page {first} of {count}."]
        if not any(pages):
            lines.append("There is no text on them.")
    else:
        lines = [f"{src} — {count} page{'' if count == '1' else 's'}" + (f", titled \"{field('Title')}\"" if field("Title") else "")
                 + (f", {field('Page size')}" if field("Page size") else "") + "."]
    total, held = 0, []
    for n, page in enumerate(pages, first):
        if not page:
            continue
        shown = page[:_PDF_TEXT_PAGE]
        rows = tables[n - first] if n - first < len(tables) else []
        # A reply's worth: the model reads what is here, and asks for the pages after it.
        if total and total + len(shown) + sum(map(len, rows)) > _PDF_TEXT_ALL:
            lines.append(f"\n(Pages {n}–{end} are not shown here: extract {{\"path\": {json.dumps(src, ensure_ascii=False)}, "
                         f"\"pages\": \"{n}-{end}\"}} reads on.)")
            break
        total += len(shown) + sum(map(len, rows))
        held.append(n)
        lines.append(f"\nPage {n}:\n{shown}" + (" […]" if len(page) > len(shown) else ""))
        if rows:
            lines.append("Its tables, as they are laid out:\n" + "\n".join(rows))
    if span and held:      # its first line names the pages it holds, not the range that was asked for
        lines[0] = f"{src} — pages {held[0]}–{held[-1]} of {count}." if held[-1] > held[0] else f"{src} — page {held[0]} of {count}."
    if span:
        if shaped > 20:
            lines.append(f"\nIts text can't be trusted as it stands (Arabic saved as drawn glyphs): take the wording from the pages themselves — {look} shows one.")
        return "\n".join(lines)
    if scan:
        lines.append(f"It is a scan — pictures of its pages, with no text in it. Look at a page with {look} (then 2, 3 …) "
                     "and take its words from what you see.")
    elif shaped > 20:
        lines.append(f"\nIts text can't be trusted as it stands: the Arabic is saved as the glyphs it was drawn with, so letters "
                     f"may be doubled and lines out of order. Take the wording from the pages themselves — {look} shows one.")
    if pictures:
        lines.append("\nIts pictures, saved to use again:")
        lines += [f"  {rel} ({w}×{h})" for rel, (w, h) in pictures]
        lines.append(f"Use one in a document as {{\"image\": \"{pictures[0][0]}\", \"caption\": \"…\"}} (or as the cover's `image`).")
    elif not scan:
        lines.append("\nIt has no pictures stored in it (photos of 200px or more).")
    if not scan:
        lines.append(f"A chart or a diagram that is drawn in the PDF is not a picture in it. To use one again, look at its page — {look} — "
                     "and cut it out: the same with \"area\": [left, top, width, height], each a part of the page from 0 to 1.")
    lines.append("To redesign it: write its content as a `document` — its own sections and words, better organised — and render that.")
    return "\n".join(lines)


async def _pdf_page(inp, workspace, name, path, src):
    """One page of a PDF drawn for the model to look at — or, with `area`, that part of it
    cut out and saved to designs/<name>-assets/figure-<n>.png: a chart or a diagram that is
    drawn in the PDF (so not among its pictures), to be used again in the redesign."""
    import tempfile
    page, area = inp.get("page"), inp.get("area")
    how = "`area` is [left, top, width, height], each a part of the page from 0 to 1 — e.g. [0.1, 0.25, 0.8, 0.3]"
    if isinstance(page, str) and page.strip().isdigit():
        page = int(page)
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        return "Error: `page` is the PDF's page number, from 1."
    if area is not None:
        if isinstance(area, str):
            try:
                area = json.loads(area)
            except ValueError:
                return f"Error: {how}."
        if not (isinstance(area, (list, tuple)) and len(area) == 4
                and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in area)):
            return f"Error: {how}."
        x, y, w, h = map(float, area)
        if not (0 <= x < 1 and 0 <= y < 1 and w >= 0.02 and h >= 0.02 and x + w <= 1.001 and y + h <= 1.001):
            return f"Error: {how} — this one runs off the page."
    which = ("-f", str(page), "-l", str(page))
    try:
        _, info = await _run_tool("pdfinfo", *which, str(path), timeout=20)
        info = info.decode("utf-8", "replace")
        count = int((re.search(r"^Pages:\s+(\d+)", info, re.M) or [0, 0])[1])
        if count and page > count:
            return f"Error: {src} has {count} pages."
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "page"
            if area is None:
                await _run_tool("pdftoppm", "-r", str(_PDF_LOOK_DPI), *which, "-jpeg", "-singlefile", str(path), str(out), timeout=60)
                made = out.with_suffix(".jpg")
            else:
                paper = re.search(r"^Page\s+(?:\d+\s+)?size:\s+([\d.]+) x ([\d.]+)", info, re.M)
                if not paper:
                    return f"Error: couldn't read the size of page {page} of {src}."
                W, H = (round(float(v) * _PDF_CUT_DPI / 72) for v in paper.groups())
                await _run_tool("pdftoppm", "-r", str(_PDF_CUT_DPI), *which, "-x", str(round(x * W)), "-y", str(round(y * H)),
                                "-W", str(round(w * W)), "-H", str(round(h * H)), "-png", "-singlefile", str(path), str(out), timeout=60)
                made = out.with_suffix(".png")
            if not made.is_file():
                return f"Error: page {page} of {src} couldn't be drawn — it may be damaged or locked with a password."
            data = await asyncio.to_thread(made.read_bytes)
    except FileNotFoundError:
        return "Error: reading a PDF's pages needs poppler (pdfinfo, pdftoppm) in this agent's image."
    except asyncio.TimeoutError:
        return f"Error: page {page} of {src} took too long to draw."
    said = json.dumps(src, ensure_ascii=False)
    if area is None:
        text = (f"Page {page} of {count or '?'} of {src}. To use a chart or a diagram on it again, cut it out: extract "
                f"{{\"path\": {said}, \"page\": {page}, \"area\": [left, top, width, height]}} — each a part of the page from 0 to 1 "
                f"(its top-left quarter is [0, 0, 0.5, 0.5]).")
        media = "image/jpeg"
    else:
        folder = pathlib.Path(workspace.root) / "designs" / f"{name}-assets"

        def save():
            folder.mkdir(parents=True, exist_ok=True)
            n = 1 + len(list(folder.glob("figure-*.png")))
            (folder / f"figure-{n}.png").write_bytes(data)
            return n
        n = await asyncio.to_thread(save)
        rel, size = f"designs/{name}-assets/figure-{n}.png", _image_size(data) or (0, 0)
        text = (f"Saved {rel} ({size[0]}×{size[1]}) — page {page} of {src}, cut at {[round(v, 3) for v in (x, y, w, h)]}. "
                f"Check it holds the whole figure and nothing beside it; if it doesn't, cut again with the area put right. "
                f"Use it in a document as {{\"image\": \"{rel}\", \"caption\": \"…\"}}.")
        media = "image/png"
    if len(data) > _DESIGN_QA_MAX:
        return text
    return {"_model": [{"type": "image", "source": {"type": "base64", "media_type": media, "data": base64.b64encode(data).decode()}},
                       {"type": "text", "text": text}]}
