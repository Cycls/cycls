# uv run cycls deploy examples/function/scrape.py --remote
import cycls

@cycls.function(image=cycls.Image().pip("httpx", "beautifulsoup4"))
def scrape(url):
    import httpx
    from bs4 import BeautifulSoup
    try:
        html = httpx.get(url, timeout=20, follow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0"}).text
    except Exception as e:
        return {"url": url, "error": str(e)}         # per-item failure, not a crash
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    title = (soup.title.string or "").strip() if soup.title else ""
    text = " ".join(soup.get_text(" ").split())
    return {"url": url, "title": title, "text": text[:3000]}

# Read 12 pages in parallel — seconds, not a sequential slog.
# import cycls
# urls = [f"https://en.wikipedia.org/wiki/{t}" for t in
#         ("Python_(programming_language)", "Rust_(programming_language)",
#             "Go_(programming_language)", "JavaScript", "Haskell", "Lua",
#             "Elixir_(programming_language)", "Zig_(programming_language)",
#             "Clojure", "OCaml", "Erlang_(programming_language)", "Scala_(programming_language)")]
# for page in cycls.remote("scrape").map(urls):
#     print(f"{len(page.get('text','')):>5} chars  {page['title']}")
