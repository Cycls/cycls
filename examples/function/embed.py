# uv run cycls deploy examples/function/embed.py
import cycls

@cycls.function(image=cycls.Image().pip("fastembed"))
def embed(texts, _model={}):
    # `_model` persists across calls on an instance — the model loads once
    # (first call), then every call after is warm.
    if "m" not in _model:
        from fastembed import TextEmbedding
        _model["m"] = TextEmbedding("BAAI/bge-small-en-v1.5")
    return [v.tolist() for v in _model["m"].embed(list(texts))]

# A self-hosted embedding API — semantic similarity from any machine:
# import cycls
# v = cycls.remote("embed")(["the cat sat on the mat",
#                            "a feline rested on the rug",
#                            "stock markets fell sharply today"])
# cos = lambda a, b: sum(x*y for x, y in zip(a, b)) / (sum(x*x for x in a)**.5 * sum(y*y for y in b)**.5)
# print(f"cat~feline {cos(v[0], v[1]):.2f}   cat~markets {cos(v[0], v[2]):.2f}")
