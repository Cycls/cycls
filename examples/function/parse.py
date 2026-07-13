# uv run cycls deploy examples/function/parse.py
import cycls

@cycls.function(image=cycls.Image().pip("liteparse", "httpx"))
def parse(url):
    import httpx
    from liteparse import LiteParse
    try:
        pdf = httpx.get(url, timeout=30, follow_redirects=True).content
        result = LiteParse(output_format="markdown").parse(pdf)
    except Exception as e:
        return {"url": url, "error": str(e)}         # per-document failure, not a crash
    return {"url": url, "pages": len(result.pages), "markdown": result.text}


# Parse 3 research papers in parallel:
# import cycls
# papers = cycls.remote("parse").map([f"https://arxiv.org/pdf/{p}" for p in
#     ("1706.03762", "1810.04805", "2005.14165")])
# for p in papers:
#     print(f"{p['pages']:>3} pages  {p['markdown'][:70]}")
