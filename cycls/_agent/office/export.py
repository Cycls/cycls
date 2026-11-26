"""`sheets` export and `docs` export: the workbook or document as a PDF beside it, as it prints.

The PDF is made by LibreOffice on the cycls-office service (`client.convert`), the same converter the canvas
preview and the editors' print use, with the fonts Office files ask for. It is the file to hand over when the
person asks for a PDF, not a way to look at an edit: `sheets` / `docs` read is that.
"""
import asyncio

from ..design.store import load_fig, write_fig
from . import client


async def export_pdf(workspace, path, rel, what):
    """`path` (at `rel` in the workspace) → `<name>.pdf` beside it; what the model and the canvas are told."""
    data, _ = await load_fig(workspace.root, rel)   # as the edits see it: the bucket in production
    if data is None:
        return f"Error: {rel} does not exist."
    pdf = await client.convert(data, path.name, "pdf", user_id=getattr(workspace, "subject", None))
    out = path.with_suffix(".pdf")
    out_rel = out.relative_to(workspace.root).as_posix()
    existed = await asyncio.to_thread(out.exists)
    # Through the versions, like every file the agent changes: a PDF already there (one the person uploaded) is
    # kept as the version before, never lost.
    await write_fig(workspace.root, out_rel, pdf, by="agent", reason="agent", intent=f"{what.capitalize()} as PDF")
    from ..tools import pdf as _pdf   # here, not at the top: the tools package imports this one
    pages = await _pdf.page_count(out)
    size = f"{pages} page{'s' if pages != 1 else ''}, " if pages else ""
    return {"_model": (f"Saved {out_rel} ({size}{max(1, len(pdf) // 1024)} KB): the {what} as it prints. "
                       + ("The PDF that was there is kept in its versions. " if existed else "")
                       + "Give the person this path."),
            "_ui": {"type": "ui", "action": "open_canvas", "path": out_rel}}
