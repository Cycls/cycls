"""PDF extraction helpers. Uses poppler-utils (pdfinfo, pdftoppm)."""
import asyncio, base64, pathlib, re, tempfile

MAX_PAGES_PER_READ = 20
EXTRACT_SIZE_THRESHOLD = 3 * 1024 * 1024  # 3 MB
DPI = 72

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

async def extract(path, first, last):
    """Render a PDF page range to JPGs via pdftoppm. Returns API content blocks or error string."""
    if last < first:
        return f"Error: invalid range {first}-{last}"
    if last - first + 1 > MAX_PAGES_PER_READ:
        return f"Error: max {MAX_PAGES_PER_READ} pages per read"
    with tempfile.TemporaryDirectory() as tmp:
        proc = await asyncio.create_subprocess_exec(
            "pdftoppm", "-jpeg", "-r", str(DPI),
            "-f", str(first), "-l", str(last),
            str(path), f"{tmp}/page",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = stderr.decode(errors="replace")[:200]
            if "password" in err.lower():
                return "Error: PDF is password-protected"
            if re.search(r"damaged|corrupt|invalid", err, re.I):
                return "Error: PDF is corrupted or invalid"
            return f"Error extracting PDF: {err}"
        jpgs = sorted(pathlib.Path(tmp).glob("page-*.jpg"))
        if not jpgs:
            return "Error: pdftoppm produced no output pages"
        return [{
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg",
                       "data": base64.b64encode(p.read_bytes()).decode()}
        } for p in jpgs]
