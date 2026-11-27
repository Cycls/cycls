"""PDF helpers over poppler-utils (pdfinfo, pdftoppm, pdfseparate)."""
import asyncio, base64, io, pathlib, re, tempfile

MAX_PAGES_PER_READ = 20
SCANS_PER_DOCUMENT = 100   # pages of one document read off their pictures in a chat: time and cost stay bounded
EXTRACT_SIZE_THRESHOLD = 3 * 1024 * 1024  # 3 MB
DPI = 150        # a page looked at: a chart, a stamp, the layout
READ_DPI = 300   # a page read off its picture, in strips: each strip then fills the model's picture budget
STRIPS = 3       # a whole page in one picture loses small digits (٥٣ read as ٥٢); a third of one keeps them

async def page_count(path):
    """Return PDF page count via pdfinfo, or None if unavailable."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "pdfinfo", str(path),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        m = re.search(rb"^Pages:\s+(\d+)", stdout, re.M)
        return int(m.group(1)) if m else None
    except Exception:
        return None

def parse_pages(spec):
    """Parse '1-5' or '3' → (first, last). Returns None on invalid input."""
    if not spec: return None
    try:
        if "-" in spec:
            f, l = spec.split("-", 1)
            return int(f), int(l)
        n = int(spec)
        return n, n
    except ValueError:
        return None

def check(first, last):
    """Why a page range can't be read, or None."""
    if last < first: return f"Error: invalid range {first}-{last}"
    if last - first + 1 > MAX_PAGES_PER_READ: return f"Error: max {MAX_PAGES_PER_READ} pages per read"

async def _poppler(*argv):
    """Run a poppler tool: None, or the error it ended with."""
    proc = await asyncio.create_subprocess_exec(*argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, stderr = await proc.communicate()
    if proc.returncode == 0: return None
    err = stderr.decode(errors="replace")[:200]
    if "password" in err.lower(): return "Error: PDF is password-protected"
    if re.search(r"damaged|corrupt|invalid", err, re.I): return "Error: PDF is corrupted or invalid"
    return f"Error extracting PDF: {err}"

async def extract(path, first, last):
    """Render a PDF page range to JPGs via pdftoppm. Returns API content blocks or error string."""
    if err := check(first, last): return err
    with tempfile.TemporaryDirectory() as tmp:
        if err := await _poppler("pdftoppm", "-jpeg", "-r", str(DPI), "-f", str(first), "-l", str(last),
                                 str(path), f"{tmp}/page"):
            return err
        jpgs = sorted(pathlib.Path(tmp).glob("page-*.jpg"))
        if not jpgs:
            return "Error: pdftoppm produced no output pages"
        return [{
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg",
                       "data": base64.b64encode(p.read_bytes()).decode()}
        } for p in jpgs]

async def split(path, first, last):
    """Pages first..last, each a PDF of its own (bytes), or an error string."""
    with tempfile.TemporaryDirectory() as tmp:
        if err := await _poppler("pdfseparate", "-f", str(first), "-l", str(last), str(path), f"{tmp}/%d.pdf"):
            return err
        return [(pathlib.Path(tmp) / f"{n}.pdf").read_bytes() for n in range(first, last + 1)]

async def strips(path, n):
    """Page n as pictures to read: cut across at its emptiest rows near even thirds, so no line is cut in two,
    and blank parts left out; the whole page when Pillow is missing. An error string when it can't be drawn."""
    with tempfile.TemporaryDirectory() as tmp:
        if err := await _poppler("pdftoppm", "-jpeg", "-r", str(READ_DPI), "-f", str(n), "-l", str(n),
                                 "-singlefile", str(path), f"{tmp}/p"):
            return err
        jpg = (pathlib.Path(tmp) / "p.jpg").read_bytes()
    try: return await asyncio.to_thread(_cut, jpg)
    except ImportError: return [jpg]

def _cut(jpg, n=STRIPS):
    from PIL import Image
    im = Image.open(io.BytesIO(jpg)).convert("L")
    w, h = im.size
    ink = im.point(lambda p: 255 if p < 128 else 0).resize((1, h), Image.BOX).tobytes()   # each row's share of dark
    r = h // (4 * n)
    cuts = [0, *(min(range(t - r, t + r + 1), key=lambda y: (sum(ink[max(y - 3, 0):y + 4]), abs(y - t)))   # mid-gap
                 for t in (h * k // n for k in range(1, n))), h]
    out = []
    for a, b in zip(cuts, cuts[1:]):
        if max(ink[a:b], default=0) >= 3:   # something is written there
            buf = io.BytesIO()
            im.crop((0, a, w, b)).save(buf, "JPEG", quality=85)
            out.append(buf.getvalue())
    return out
