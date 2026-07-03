"""Model catalog — context window, output cap, and USD pricing per model.

Bundled entries are authoritative for the models we ship against; models.dev
fills the gaps for anything newer (fetched in the background, cached 24h).
Lookup is provider-aware — the same model id can carry different limits and
prices on different providers.
"""
import asyncio, json, time
from pathlib import Path

# provider → {model id/prefix: (context, max_output, in, out, cache_read, cache_write)}
# prices are USD per 1M tokens; anthropic cache_write at the 1h TTL we pin (2x input).
_BUNDLED = {
    "anthropic": {
        "claude-fable-5":    (1_000_000, 128_000, 10, 50, 1.00, 20),
        "claude-sonnet-5":   (1_000_000, 128_000, 2, 10, 0.20, 4),  # intro pricing until 2026-08-31, then 3/15
        "claude-opus-4-20250514": (200_000, 32_000, 15, 75, 1.50, 30),
        "claude-opus-4-1":   (200_000, 32_000, 15, 75, 1.50, 30),
        "claude-opus-4-5":   (200_000, 64_000, 5, 25, 0.50, 10),
        "claude-opus":       (1_000_000, 128_000, 5, 25, 0.50, 10),
        "claude-sonnet-4-6": (1_000_000, 64_000, 3, 15, 0.30, 6),
        "claude-sonnet":     (200_000, 64_000, 3, 15, 0.30, 6),
        "claude-haiku-4-5":  (200_000, 64_000, 1, 5, 0.10, 2),
        "claude-haiku":      (200_000, 8_192, 0.80, 4, 0.08, 1.60),
        "claude":            (200_000, 8_192, 0, 0, 0, 0),
    },
    "openai": {
        "gpt-5.5":      (1_050_000, 128_000, 5, 30, 0.50, 0),
        "gpt-5.4-mini": (400_000, 128_000, 0.75, 4.50, 0.075, 0),
        "gpt-5.4":      (1_050_000, 128_000, 2.50, 15, 0.25, 0),
        "gpt-5":        (400_000, 128_000, 0.625, 5, 0.0625, 0),
        "gpt-4o":       (128_000, 16_384, 2.50, 10, 1.25, 0),
    },
    "zai": {
        "glm-5.2": (1_048_576, 131_072, 1.40, 4.40, 0.26, 0),
        "glm-5":   (204_800, 131_072, 1, 3.20, 0.20, 0),
        "glm":     (200_000, 131_072, 0, 0, 0, 0),
    },
    "deepseek": {
        "deepseek-v4-pro": (1_000_000, 384_000, 0.435, 0.87, 0.003625, 0),
        "deepseek":        (1_000_000, 384_000, 0.14, 0.28, 0.0028, 0),  # v4-flash + chat/reasoner aliases
    },
    "alibaba": {
        "qwen3-coder-plus": (1_048_576, 65_536, 1, 5, 0, 0),
        "qwen3-max":        (262_144, 65_536, 1.20, 6, 0, 0),
        "qwen-plus":        (1_000_000, 32_768, 0.40, 1.20, 0, 0),
        "qwen":             (131_072, 32_768, 0, 0, 0, 0),
    },
    "moonshotai": {
        "kimi-k2.6": (262_144, 262_144, 0.95, 4, 0.16, 0),
        "kimi":      (262_144, 262_144, 0.60, 2.50, 0.15, 0),
    },
    "xai": {
        "grok": (1_000_000, 30_000, 1.25, 2.50, 0.20, 0),
    },
    "google": {
        "gemini-3.1-pro":   (1_048_576, 65_536, 2, 12, 0.20, 0),
        "gemini-3.5-flash": (1_048_576, 65_536, 1.50, 9, 0.15, 0),
        "gemini-2.5-pro":   (1_048_576, 65_536, 1.25, 10, 0.125, 0),
        "gemini":           (1_048_576, 65_536, 0, 0, 0, 0),
    },
}
_ALIASES = {"z-ai": "zai", "zhipu": "zai", "zhipuai": "zai", "glm": "zai", "bigmodel": "zai",
            "qwen": "alibaba", "dashscope": "alibaba",
            "moonshot": "moonshotai", "kimi": "moonshotai",
            "gemini": "google", "grok": "xai", "x-ai": "xai"}
_DEFAULT = (128_000, 16_384, 0, 0, 0, 0)

_CACHE = Path.home() / ".cycls" / "models.json"  # default; agents point this at the volume
_TTL = 24 * 3600
_live = None       # parsed models.dev payload
_fetching = False


def _match(table, model):
    """Exact id, else longest matching prefix/substring key."""
    if model in table: return table[model]
    hits = [k for k in table if k in model]
    return table[max(hits, key=len)] if hits else None


def _from_live(vendor, model):
    if not isinstance(_live, dict): return None
    ids = (vendor, *(a for a, c in _ALIASES.items() if c == vendor))
    for pid in ids:
        models = (_live.get(pid) or {}).get("models") or {}
        if m := _match(models, model):
            limit, cost_ = m.get("limit") or {}, m.get("cost") or {}
            return (limit.get("context") or _DEFAULT[0], limit.get("output") or _DEFAULT[1],
                    cost_.get("input") or 0, cost_.get("output") or 0,
                    cost_.get("cache_read") or 0, cost_.get("cache_write") or 0)
    return None


def _entry(vendor, model):
    vendor = _ALIASES.get(vendor, vendor)
    return _match(_BUNDLED.get(vendor, {}), model) or _from_live(vendor, model) or _DEFAULT


def context_window(vendor, model): return _entry(vendor, model)[0]
def max_output(vendor, model):     return _entry(vendor, model)[1]


def cost(vendor, model, inp, out, cached, cache_create):
    """USD for one turn (or aggregate). Unpriced model → 0."""
    _, _, pin, pout, prd, pwr = _entry(vendor, model)
    return (inp * pin + out * pout + cached * prd + cache_create * pwr) / 1_000_000


async def _fetch():
    global _live, _fetching
    import httpx
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get("https://models.dev/api.json")
        r.raise_for_status()
        _live = r.json()
        _CACHE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE.write_text(json.dumps(_live))
    except Exception:
        pass
    finally:
        _fetching = False


def refresh(cache_dir=None):
    """Load the cached models.dev snapshot; kick a background refetch when
    stale. Never blocks the turn — until the fetch lands, lookups fall back
    to the bundled table. The loop passes the deployment volume as *cache_dir*
    so the snapshot survives serverless restarts and is shared per deployment."""
    global _live, _fetching, _CACHE
    if cache_dir:
        _CACHE = Path(cache_dir) / ".cycls" / "models.json"
    if _live is None and _CACHE.exists():
        try: _live = json.loads(_CACHE.read_text())
        except Exception: _live = {}
    if _fetching or (_CACHE.exists() and time.time() - _CACHE.stat().st_mtime < _TTL):
        return
    _fetching = True
    try:
        asyncio.get_running_loop().create_task(_fetch())
    except RuntimeError:
        _fetching = False  # no running loop — sync context, skip
