"""Large tool results become files, not context. Above SPILL_AT chars the full
text lands in .tmp/{chat_id}/ and the model gets a preview and a path — then
analyses it with bash instead of reading it back. `.tmp` is hidden from
listings but deliberately readable by bash and `read`, and the rm shim passes
it through. Cleanup is lazy, like the trash: chat purge removes its directory,
and each spill sweeps chat directories idle past TTL.
"""
import json, shutil, time
from pathlib import Path

DIR = ".tmp"
SPILL_AT = 20_000
TTL = 48 * 3600
SWEEP_EVERY = 3600
PREVIEW = 2


def _describe(text):
    try:
        data = json.loads(text)
    except ValueError:
        lines = text.splitlines()
        return "txt", f"{len(lines):,} lines", "\n".join(lines[:PREVIEW * 5])[:600]
    if isinstance(data, list):
        sample = "\n".join(json.dumps(x, ensure_ascii=False)[:300] for x in data[:PREVIEW])
        return "json", f"{len(data):,} records", sample
    return "json", "one object", text[:600]


def _size(n):
    return f"{n / 1024:.0f} KB" if n < 1 << 20 else f"{n / (1 << 20):.1f} MB"


def spill(text, root, chat_id, name):
    """The model-facing replacement for *text* — or *text* itself when it is
    small, has no chat to belong to, or the write fails."""
    if len(text) < SPILL_AT or not chat_id:
        return text
    try:
        ext, count, sample = _describe(text)
        d = Path(root) / DIR / chat_id
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{name}.{ext}"
        path.write_text(text)
        _sweep(Path(root) / DIR)
    except OSError:
        return text
    return (f"Saved {_size(len(text))} to {path.relative_to(root)} ({count}). Preview:\n{sample}\n"
            "Analyse it with bash (jq, rg, python) — don't read the whole file.")


def _sweep(tmp):
    marker, now = tmp / ".sweep", time.time()
    if marker.exists() and now - marker.stat().st_mtime < SWEEP_EVERY:
        return
    marker.touch()
    for chat in tmp.iterdir():
        if chat.is_dir() and now - max((f.stat().st_mtime for f in chat.iterdir()), default=0) > TTL:
            shutil.rmtree(chat, ignore_errors=True)


def purge(root, chat_id):
    shutil.rmtree(Path(root) / DIR / chat_id, ignore_errors=True)
