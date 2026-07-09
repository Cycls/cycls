# uv run cycls deploy examples/function/extract.py
import cycls

@cycls.function(image=cycls.Image().pip("pymupdf", "httpx"))
def extract(url):
    import httpx, fitz
    try:
        pdf = httpx.get(url, timeout=30, follow_redirects=True).content
        doc = fitz.open(stream=pdf, filetype="pdf")
    except Exception as e:
        return {"url": url, "error": str(e)}         # per-document failure, not a crash
    text = " ".join(" ".join(page.get_text() for page in doc).split())
    return {"url": url, "pages": doc.page_count,
            "title": (doc.metadata.get("title") or "").strip(),
            "text": text[:5000]}


# Extract 6 research papers in parallel:
# import cycls
# papers = cycls.remote("extract").map([f"https://arxiv.org/pdf/{p}" for p in
#     ("1706.03762", "1810.04805", "2005.14165", "1512.03385", "1412.6980", "2302.13971")])
# for p in papers:
#     print(f"{p['pages']:>3} pages  {p.get('title') or p['text'][:70]}")
