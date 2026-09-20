# One call per item, across autoscaled instances, results in input order.
#
#   uv run cycls run examples/functions/fanout.py            # local Docker
#   uv run cycls run examples/functions/fanout.py --remote   # in the cloud
import cycls

image = cycls.Image().pip("httpx", "selectolax")


@cycls.function(image=image, concurrency=1)
def read_page(url: str):
    import httpx
    from selectolax.parser import HTMLParser

    try:
        r = httpx.get(url, timeout=30, follow_redirects=True,
                      headers={"User-Agent": "cycls-example/1.0"})
    except Exception as e:
        # A returned error keeps one bad item from sinking the batch:
        # `.map()` raises on the first exception it sees.
        return {"url": url, "error": str(e)}

    tree = HTMLParser(r.text)
    for tag in tree.css("script, style, noscript"):
        tag.decompose()
    title = tree.css_first("title")
    return {
        "url": url,
        "status": r.status_code,
        "title": title.text().strip() if title else None,
        "chars": len(tree.text()),
    }


PAGES = [f"https://en.wikipedia.org/wiki/{t}" for t in (
    "Python_(programming_language)", "Rust_(programming_language)",
    "Go_(programming_language)", "JavaScript", "Haskell", "Lua",
)]


@cycls.local_entrypoint
def main():
    # The entrypoint runs on your machine. The verbs inside it decide where the
    # work happens, which is why `--remote` does not apply here.
    for page in read_page.map(PAGES):
        if "error" in page:
            print(f"  failed  {page['url']}: {page['error']}")
        else:
            print(f"{page['chars']:>7} chars  {page['title']}")
