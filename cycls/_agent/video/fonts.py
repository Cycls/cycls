"""The workspace's own fonts for video: the brand kit's font files, brand/fonts/*.ttf|otf.

Each file is read here for what CSS needs — its family (the typographic family, else the family
name), weight and italic, and whether it draws Arabic — straight from the font's own tables, so the
guide can name the family exactly as the file has it and the model writes that. A composition that
names one of these families is sent with its files (`for_html`); the service gives them an
@font-face for that job alone (cycls-video node/tools.mjs withWorkspaceFonts).
"""
import hashlib
import struct
from pathlib import Path

DIR = Path("brand") / "fonts"
EXT = (".ttf", ".otf")
MAX_FILES = 8
MAX_BYTES = 4 * 1024 * 1024
_SFNT = (b"\x00\x01\x00\x00", b"true", b"OTTO")
_seen = {}          # (path, size, mtime) -> what the file is


def _tables(data):
    n = struct.unpack(">H", data[4:6])[0]
    out = {}
    for i in range(n):
        tag, _, off, length = struct.unpack(">4sIII", data[12 + 16 * i:28 + 16 * i])
        out[tag.decode("latin-1")] = (off, length)
    return out


def _names(data, off):
    _, count, strings = struct.unpack(">HHH", data[off:off + 6])
    names = {}
    for i in range(count):
        pid, _, lid, nid, length, at = struct.unpack(">HHHHHH", data[off + 6 + 12 * i:off + 18 + 12 * i])
        if nid not in (1, 16):
            continue
        raw = data[off + strings + at:off + strings + at + length]
        if pid in (0, 3):
            text = raw.decode("utf-16-be", "replace")
        elif pid == 1:
            text = raw.decode("mac_roman", "replace")
        else:
            continue
        rank = 0 if (pid == 3 and lid == 0x409) or (pid == 1 and lid == 0) else 1
        if nid not in names or rank < names[nid][0]:
            names[nid] = (rank, text.strip())
    return {k: v[1] for k, v in names.items()}


def _draws_arabic(data, off):
    """Does a Unicode cmap subtable cover ALEF (U+0627)?"""
    n = struct.unpack(">H", data[off + 2:off + 4])[0]
    for i in range(n):
        pid, eid, sub = struct.unpack(">HHI", data[off + 4 + 8 * i:off + 12 + 8 * i])
        if pid not in (0, 3):
            continue
        at = off + sub
        fmt = struct.unpack(">H", data[at:at + 2])[0]
        if fmt == 4:      # segments; the glyph is worked out, since a segment may map to none (glyph 0)
            seg2 = struct.unpack(">H", data[at + 6:at + 8])[0]
            n = seg2 // 2
            ends = struct.unpack(f">{n}H", data[at + 14:at + 14 + seg2])
            starts_at = at + 16 + seg2
            starts = struct.unpack(f">{n}H", data[starts_at:starts_at + seg2])
            deltas = struct.unpack(f">{n}h", data[starts_at + seg2:starts_at + 2 * seg2])
            ranges_at = starts_at + 2 * seg2
            ranges = struct.unpack(f">{n}H", data[ranges_at:ranges_at + seg2])
            for k, (s, e) in enumerate(zip(starts, ends)):
                if not s <= 0x0627 <= e:
                    continue
                if ranges[k] == 0:
                    glyph = (0x0627 + deltas[k]) & 0xFFFF
                else:
                    g_at = ranges_at + 2 * k + ranges[k] + 2 * (0x0627 - s)
                    glyph = struct.unpack(">H", data[g_at:g_at + 2])[0]
                    glyph = (glyph + deltas[k]) & 0xFFFF if glyph else 0
                if glyph:
                    return True
        elif fmt == 12:
            groups = struct.unpack(">I", data[at + 12:at + 16])[0]
            for g in range(min(groups, 100_000)):
                s, e, _ = struct.unpack(">III", data[at + 16 + 12 * g:at + 28 + 12 * g])
                if s <= 0x0627 <= e:
                    return True
    return False


def read(data):
    """A TrueType or OpenType font's {family, weight, style, arabic}, or None when it is not one."""
    if not isinstance(data, (bytes, bytearray)) or data[:4] not in _SFNT:
        return None
    try:
        t = _tables(data)
        names = _names(data, t["name"][0]) if "name" in t else {}
        family = names.get(16) or names.get(1)
        if not family:
            return None
        weight, italic = 400, False
        if "OS/2" in t:
            off = t["OS/2"][0]
            weight = struct.unpack(">H", data[off + 4:off + 6])[0] or 400
            italic = bool(struct.unpack(">H", data[off + 62:off + 64])[0] & 1)
        arabic = _draws_arabic(data, t["cmap"][0]) if "cmap" in t else False
    except (struct.error, KeyError, IndexError, ValueError):
        return None
    return {"family": " ".join(family.split())[:64], "weight": max(1, min(1000, int(weight))),
            "style": "italic" if italic else "normal", "arabic": arabic}


def workspace(root):
    """The brand kit's fonts: [{path, family, weight, style, arabic, bytes}], at most MAX_FILES, each
    at most MAX_BYTES; files that are not fonts are left out."""
    d = Path(root) / DIR
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.iterdir()):
        if len(out) >= MAX_FILES:
            break
        if not p.is_file() or p.suffix.lower() not in EXT:
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        if st.st_size > MAX_BYTES:
            continue
        key = (str(p), st.st_size, st.st_mtime_ns)
        if key not in _seen:
            try:
                _seen[key] = read(p.read_bytes())
            except OSError:
                _seen[key] = None
        if _seen[key]:
            out.append({"path": (DIR / p.name).as_posix(), **_seen[key], "bytes": st.st_size})
    return out


def families(root):
    """{family: {"weights": [..], "arabic": bool}} of the brand kit's fonts."""
    out = {}
    for f in workspace(root):
        fam = out.setdefault(f["family"], {"weights": [], "arabic": False})
        fam["weights"] = sorted(set(fam["weights"] + [f["weight"]]))
        fam["arabic"] = fam["arabic"] or f["arabic"]
    return out


def for_html(root, html):
    """The brand fonts a composition names, ready to send: ({hashed file: {family, weight, style,
    arabic}}, {hashed file: bytes}); ({}, {}) when it names none."""
    low = (html or "").lower()
    meta, files = {}, {}
    for f in workspace(root):
        if f["family"].lower() not in low:
            continue
        try:
            data = (Path(root) / f["path"]).read_bytes()
        except OSError:
            continue
        name = hashlib.sha256(data).hexdigest()[:32] + Path(f["path"]).suffix.lower()
        meta[name] = {k: f[k] for k in ("family", "weight", "style", "arabic")}
        files[name] = data
    return meta, files
