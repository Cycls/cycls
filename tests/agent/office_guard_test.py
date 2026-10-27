"""Bash kept off the Word and Excel files `docs` and `sheets` look after (cycls/_agent/office/guard.py)."""
import asyncio
import types

import pytest

from cycls._agent import tools
from cycls._agent.office import guard

DOCS = frozenset({"docs"})
BOTH = frozenset({"docs", "sheets"})


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "docs-test").mkdir()
    (tmp_path / "docs-test" / "layout.docx").write_bytes(b"PK\x03\x04 word")
    (tmp_path / "docs-test" / "شكر المبيعات.docx").write_bytes(b"PK\x03\x04 word")
    (tmp_path / "finance").mkdir()
    (tmp_path / "finance" / "budget.xlsx").write_bytes(b"PK\x03\x04 book")
    return tmp_path


@pytest.mark.parametrize("command", [
    "unzip -p docs-test/layout.docx word/document.xml | head -c 2000",
    "python3 -c \"import zipfile; z = zipfile.ZipFile('docs-test/layout.docx'); print(z.namelist())\"",
    "python3 - <<'EOF'\nimport zipfile\nz = zipfile.ZipFile('/workspace/docs-test/شكر المبيعات.docx')\nEOF",
    "cd docs-test && unzip -l layout.docx",
    # seen live: a scratch folder made, then the file named from inside it
    "mkdir -p .tmp/q3x && cd .tmp/q3x && unzip -o -q ../../docs-test/layout.docx && find . -type f | sort",
    "cd docs-test; cd ..; unzip -l docs-test/layout.docx",
    "for f in docs-test/*.docx; do unzip -l \"$f\"; done",
    "python3 -c \"from docx import Document; d = Document('docs-test/layout.docx'); d.save('docs-test/layout.docx')\"",
])
def test_opening_a_word_file_is_refused(ws, command):
    out = guard.refusal(command, ws, DOCS)
    assert out and out.startswith("Error: not run") and "`docs`" in out


@pytest.mark.parametrize("command", [
    "cp docs-test/layout.docx docs-test/layout-v2.docx",
    "ls -la docs-test/ && file docs-test/layout.docx",
    "mv 'docs-test/شكر المبيعات.docx' docs-test/thanks.docx",
    "python3 -c \"import zipfile; zipfile.ZipFile('other/new.docx', 'w').close()\"",   # a file not there yet
    "unzip -l archive.zip",
])
def test_other_commands_run(ws, command):
    assert guard.refusal(command, ws, DOCS) is None


def test_only_while_the_tool_is_on(ws):
    command = "unzip -p docs-test/layout.docx word/document.xml"
    assert guard.refusal(command, ws, frozenset()) is None
    assert guard.refusal(command, ws, frozenset({"sheets"})) is None
    assert guard.refusal(command, ws, BOTH)


def test_excel(ws):
    assert "`sheets`" in guard.refusal("python3 -c \"import openpyxl; openpyxl.load_workbook('finance/budget.xlsx')\"", ws, BOTH)
    assert guard.refusal("python3 -c \"import pandas as pd; df = pd.read_excel('finance/budget.xlsx'); df.to_excel('finance/budget.xlsx')\"", ws, BOTH)
    # pandas reading for analysis, with or without openpyxl named as its engine
    assert guard.refusal("python3 -c \"import pandas as pd; print(pd.read_excel('finance/budget.xlsx').sum())\"", ws, BOTH) is None
    assert guard.refusal("python3 -c \"import pandas as pd; pd.read_excel('finance/budget.xlsx', engine='openpyxl')\"", ws, BOTH) is None
    assert guard.refusal("python3 -c \"import openpyxl; openpyxl.load_workbook('finance/budget.xlsx')\"", ws, DOCS) is None


def test_a_script_that_opens_it(ws):
    (ws / "inspect.py").write_text("import zipfile\nprint(zipfile.ZipFile('docs-test/layout.docx').namelist())\n")
    assert guard.refusal("python3 inspect.py", ws, DOCS)
    (ws / "count.py").write_text("print(1 + 1)\n")
    assert guard.refusal("python3 count.py", ws, DOCS) is None


def test_a_file_the_turn_built_may_be_checked(ws):
    build = "python3 build.py && echo saved reports/q3.docx"
    before = guard.missing(build, ws)
    assert before == [str((ws / "reports" / "q3.docx").resolve())]
    (ws / "reports").mkdir()
    (ws / "reports" / "q3.docx").write_bytes(b"PK")
    built = guard.made(before)
    check = "python3 -c \"import zipfile; zipfile.ZipFile('reports/q3.docx').read('word/document.xml')\""
    assert guard.refusal(check, ws, DOCS, built) is None
    assert guard.refusal(check, ws, DOCS)   # a later turn: an existing file like any other


def _ctx(ws, office):
    return tools.ToolContext(user=None, workspace=types.SimpleNamespace(root=str(ws)), office=office)


def test_dispatch_refuses_before_running(ws, monkeypatch):
    ran = []

    async def fake_exec(command, cwd, **_):
        ran.append(command)
        return "ran"
    monkeypatch.setattr(tools, "_exec_bash", fake_exec)
    workspace = types.SimpleNamespace(root=str(ws))
    block = {"id": "b1", "name": "bash", "input": {"command": "unzip -p docs-test/layout.docx word/document.xml"}}
    step, result = tools.dispatch(block, workspace, 60, ctx=_ctx(ws, DOCS))
    assert step["ok"] is False
    assert asyncio.run(result).startswith("Error: not run")
    assert ran == []
    # the same command with Docs off runs
    step, result = tools.dispatch(block, workspace, 60, ctx=_ctx(ws, frozenset()))
    assert asyncio.run(result) == "ran" and ran


def test_dispatch_remembers_what_bash_made(ws, monkeypatch):
    async def fake_exec(command, cwd, **_):
        (ws / "out.docx").write_bytes(b"PK")
        return "saved"
    monkeypatch.setattr(tools, "_exec_bash", fake_exec)
    workspace = types.SimpleNamespace(root=str(ws))
    ctx = _ctx(ws, DOCS)
    build = {"id": "b1", "name": "bash", "input": {"command": "python3 -c \"from docx import Document; Document().save('out.docx')\""}}
    _, result = tools.dispatch(build, workspace, 60, ctx=ctx)
    assert asyncio.run(result) == "saved"
    check = {"id": "b2", "name": "bash", "input": {"command": "python3 -c \"import zipfile; zipfile.ZipFile('out.docx').namelist()\""}}
    step, result = tools.dispatch(check, workspace, 60, ctx=ctx)
    assert step.get("ok") is not False and asyncio.run(result) == "saved"
