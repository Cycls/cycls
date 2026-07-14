"""cycls CLI — run, deploy, list, delete, logs, and scaffold agents."""
import argparse
import os
import sys
import time
from pathlib import Path


# ---- Module loading ----

def _load_target(path_spec):
    """Import a file; return (target, entrypoint) — the first
    @cycls.function/app/agent instance and the file's @cycls.local_entrypoint
    (None if undeclared). `path_spec` is 'file.py' or 'file.py::name'."""
    if "::" in path_spec:
        path_str, target = path_spec.split("::", 1)
    else:
        path_str, target = path_spec, None

    from cycls.function.remote import _load_module
    module = _load_module(path_str)
    path = Path(path_str).resolve()

    from cycls.function import Function
    from cycls.app import App

    entry = next((o for o in vars(module).values()
                  if getattr(o, "_cycls_entry", False)), None)

    if target:
        obj = getattr(module, target, None)
        if obj is None:
            sys.exit(f"Error: target '{target}' not found in {path}")
        return obj, entry

    for _, obj in module.__dict__.items():
        if isinstance(obj, (Function, App)):
            return obj, entry

    sys.exit(f"Error: no @cycls.function/app/agent instance found in {path}")


# ---- API client ----

def _api(method, path, **kwargs):
    """Call the Cycls API with the user's API key."""
    import httpx
    from cycls.function.main import _get_api_key, _get_base_url

    api_key = _get_api_key()
    if not api_key:
        sys.exit("Error: no API key. Set CYCLS_API_KEY or cycls.api_key.")

    base_url = _get_base_url() or "https://api.cycls.ai"
    kwargs.setdefault("timeout", 30)
    resp = httpx.request(
        method, f"{base_url}{path}",
        headers={"X-API-Key": api_key},
        **kwargs,
    )
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        sys.exit(f"Error: {resp.status_code} {detail}")
    return resp


# ---- Commands ----

def _pretty_log(msg):
    """Colorize hypercorn's `200 GET /path` access lines and hide the dev
    loop's own traffic. Everything else — app output, tracebacks — passes
    through untouched."""
    msg = msg.rstrip()
    parts = msg.split()
    if len(parts) != 3 or not parts[0].isdigit():
        return msg or None
    status, method, path = parts
    if path.startswith("/_cycls/"):
        return None
    color = 32 if int(status) < 300 else 33 if int(status) < 500 else 31
    return f"\033[{color}m{status}\033[0m {method} {path}"


def _stream_logs(name, stop):
    """Live-tail the dev service's own log stream (/_cycls/logs). Started once
    the service is up, so a 404 means it predates the endpoint."""
    import httpx
    from cycls.function.main import _get_api_key
    from cycls.function.remote import token_for
    headers = {"X-Cycls-Token": token_for(_get_api_key(), name)}
    while not stop.is_set():
        try:
            with httpx.stream("GET", f"https://{name}.cycls.ai/_cycls/logs",
                              timeout=httpx.Timeout(30, connect=5), headers=headers) as r:
                if r.status_code == 404:
                    print(f"  \033[2m│ no live logs on this service — `cycls rm {name}`, then save\033[0m",
                          flush=True)
                    return
                for raw in r.iter_lines():
                    if stop.is_set():
                        return
                    if (line := _pretty_log(raw or "")):
                        print(f"  \033[2m│\033[0m {line}", flush=True)
        except httpx.HTTPError:
            pass
        stop.wait(2)


def _watch_loop(instance, script, argv, remote, after_first=None):
    import subprocess
    from watchfiles import watch
    paths = [script] + [str(Path(p).resolve()) for p in instance.copy if Path(p).exists()]
    drive = [sys.executable, "-c",
             f"from cycls.function.remote import _drive; _drive({script!r}, {tuple(argv)!r}, {remote!r})"]
    print(f"{instance.name} — rerunning on save (Ctrl-C to stop)\n", flush=True)
    try:
        first = subprocess.run(drive)
        if after_first and first.returncode == 0:
            after_first()
        for changes in watch(*paths, raise_interrupt=False):
            print(f"↻ {Path(next(iter(changes))[1]).name}", flush=True)
            subprocess.run(drive)
    except KeyboardInterrupt:
        pass


def cmd_run(args):
    instance, entry = _load_target(args.file)
    instance._source_file = Path(args.file).resolve()
    script = str(Path(args.file).resolve())
    if entry:
        if args.remote:
            sys.exit("--remote conflicts with @cycls.local_entrypoint — the driver's code chooses run/remote")
        _watch_loop(instance, script, args.args, remote=False)
    elif hasattr(instance, "local"):
        if args.remote:
            import threading
            from cycls.agent.main import Agent
            if isinstance(instance, Agent):
                sys.exit("live cloud dev for agents isn't wired yet — `cycls run` (Docker) or `cycls deploy`")
            stop = threading.Event()
            tail = threading.Thread(target=_stream_logs, args=(instance.dev_name, stop), daemon=True)
            _watch_loop(instance, script, args.args, remote=True, after_first=tail.start)
            stop.set()
        else:
            instance.local()
    elif instance._is_remote():
        _watch_loop(instance, script, args.args, remote=args.remote)
    elif args.remote:
        sys.exit(f"'{instance.name}' takes a port — it's a server; run it locally or `cycls deploy`")
    else:
        instance.run()


def cmd_deploy(args):
    instance, _ = _load_target(args.file)
    instance.deploy()


def cmd_shell(args):
    """Interactive bash inside the target's built image — same env as run/deploy."""
    import subprocess
    instance, _ = _load_target(args.file)
    tag = instance._ensure_local_image()
    print(f"Entering {tag} (exit to leave)")
    subprocess.run(["docker", "run", "--rm", "-it", "--entrypoint", "bash", tag])


def cmd_ls(args):
    services = _api("GET", "/v1/deployment/list").json()
    if not services:
        print("No deployments.")
        return
    width = max((len(s.get("name", "")) for s in services), default=10)
    for svc in services:
        name = svc.get("name", "?")
        url = svc.get("url", "")
        region = svc.get("region", "")
        created = svc.get("created_at", "")
        print(f"{name:<{width}}  {url}  [{region}]  {created}")


def cmd_rm(args):
    if not args.yes:
        confirm = input(f"Delete '{args.name}'? [y/N] ").strip().lower()
        if confirm != "y":
            return
    resp = _api("POST", "/v1/deployment/delete", json={"name": args.name})
    print(resp.json().get("detail", "deleted"))


def _parse_since(s):
    """'30m' / '24h' / '7d' → absolute RFC-3339 UTC timestamp N units ago."""
    if not s: return None
    import re
    from datetime import datetime, timedelta, timezone
    m = re.fullmatch(r"(\d+)([smhd])", s)
    if not m: sys.exit(f"Error: invalid --since '{s}' (use e.g. 30m, 24h, 7d)")
    mult = {"s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]
    when = datetime.now(timezone.utc) - timedelta(seconds=int(m.group(1)) * mult)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def _join_query(*parts):
    return " AND ".join(p for p in parts if p)


def cmd_logs(args):
    query = _join_query(args.query, f'timestamp >= "{_parse_since(args.since)}"' if args.since else None)
    cursor = None
    while True:
        body = {"deployment_name": args.name, "limit": 100}
        if cursor: body["since"] = cursor
        if query: body["query"] = query
        data = _api("POST", "/v1/deployment/logs", json=body).json()
        for log in data.get("logs", []):
            ts = log.get("timestamp", "")
            sev = log.get("severity", "INFO")
            msg = log.get("message", "")
            print(f"{ts}  [{sev}]  {msg}")
        cursor = data.get("cursor")
        if not args.follow: return
        time.sleep(2)


def _month_window(spec):
    """`spec` is True (= current month) or 'YYYY-MM'. Returns (start, end, label)."""
    import re
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    if spec is True:
        year, mo = now.year, now.month
    else:
        m = re.fullmatch(r"(\d{4})-(\d{2})", spec)
        if not m: sys.exit(f"Error: invalid --month '{spec}' (use YYYY-MM)")
        year, mo = int(m.group(1)), int(m.group(2))
    start = datetime(year, mo, 1, tzinfo=timezone.utc)
    end = datetime(year + 1, 1, 1, tzinfo=timezone.utc) if mo == 12 else datetime(year, mo + 1, 1, tzinfo=timezone.utc)
    fmt = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")
    return fmt(start), fmt(end), f"{year:04d}-{mo:02d}"


def cmd_cost(args):
    """Aggregate per-turn LLM usage from the cloud — total or grouped
    by user / chat / model."""
    import json
    if args.month is not None and args.since:
        sys.exit("Error: --month and --since are mutually exclusive")
    if args.month is not None:
        start, end, label = _month_window(args.month)
        query = _join_query('jsonPayload.level="usage"',
                            f'timestamp >= "{start}"', f'timestamp < "{end}"')
    else:
        label = args.since or "24h"
        query = _join_query('jsonPayload.level="usage"', f'timestamp >= "{_parse_since(label)}"')
    cursor, entries = None, []
    while True:
        body = {"deployment_name": args.name, "limit": 1000, "query": query}
        if cursor: body["since"] = cursor
        data = _api("POST", "/v1/deployment/logs", json=body).json()
        for log in data.get("logs", []):
            msg = log.get("message", "")
            if isinstance(msg, dict): entries.append(msg); continue
            try: entries.append(json.loads(msg))
            except (json.JSONDecodeError, TypeError): pass
        cursor = data.get("cursor")
        if not cursor or not data.get("logs"): break

    if not entries:
        print(f"No usage in {label}.")
        return

    total = sum(float(e.get("cost", 0)) for e in entries)
    if not args.by:
        print(f"{args.name}  ${total:.6f}  ({len(entries)} turns, {label})")
        return

    field = {"user": "user_id", "chat": "chat_id", "model": "model"}[args.by]
    groups = {}
    for e in entries:
        key = e.get(field) or "(none)"
        g = groups.setdefault(key, [0.0, 0])
        g[0] += float(e.get("cost", 0)); g[1] += 1
    width = max(len(str(k)) for k in groups)
    for key, (cost, turns) in sorted(groups.items(), key=lambda kv: -kv[1][0]):
        print(f"{key:<{width}}  ${cost:.6f}  ({turns} turns)")


def cmd_sql(args):
    """Run SQL against your deployment data in cycls cloud. Tables:
    `logs` and `billing` — both scoped to the deployments your API key
    owns. Query from positional arg, `-f FILE`, or stdin (`-` or piped)."""
    import json as _json
    if args.query and args.query != "-":
        query = args.query
    elif args.file:
        query = Path(args.file).read_text()
    elif args.query == "-" or (not args.query and not sys.stdin.isatty()):
        query = sys.stdin.read()
    else:
        sys.exit("Error: provide a query, -f FILE, or pipe to stdin")

    fmt = args.format or ("table" if sys.stdout.isatty() else "json")
    if args.json: fmt = "json"

    # First call per deployment can take 5-10s while the server lazily
    # provisions per-tenant resources. Give it room.
    rows = _api("POST", "/v1/sql", json={"query": query}, timeout=60).json()

    if not rows:
        print("(0 rows)", file=sys.stderr)
        return

    if fmt == "json":
        sys.stdout.write(_json.dumps(rows, default=str) + "\n")
        return
    if fmt == "csv":
        import csv
        cols = list(rows[0].keys())
        w = csv.DictWriter(sys.stdout, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: _json.dumps(v) if isinstance(v, (dict, list)) else v for c, v in r.items()})
        return
    _print_table(rows)


def _print_table(rows):
    """Aligned ASCII table; nested JSON gets json.dumps; columns truncate
    to fit terminal width with a `…` suffix."""
    import json as _json, shutil
    cols = list(rows[0].keys())
    str_rows = []
    for r in rows:
        sr = []
        for c in cols:
            v = r.get(c)
            if isinstance(v, (dict, list)): v = _json.dumps(v)
            sr.append("" if v is None else str(v))
        str_rows.append(sr)
    widths = [max(len(c), max(len(r[i]) for r in str_rows)) for i, c in enumerate(cols)]
    term_w = shutil.get_terminal_size((120, 24)).columns
    if sum(widths) + 2 * (len(cols) - 1) > term_w:
        cap = max(20, (term_w - 2 * (len(cols) - 1)) // len(cols))
        widths = [min(w, cap) for w in widths]
        str_rows = [[v[:w-1] + "…" if len(v) > w else v for v, w in zip(r, widths)] for r in str_rows]
    line = "  ".join(f"{{:<{w}}}" for w in widths)
    print(line.format(*cols))
    print(line.format(*["-" * w for w in widths]))
    for r in str_rows:
        print(line.format(*r))


_STARTER_TEMPLATE = '''import cycls

image = cycls.Image()

web = (
    cycls.Web()
    .auth(cycls.Clerk())
    .title("{name}")
)

llm = (
    cycls.LLM()
    .model("anthropic/claude-sonnet-4-6")
    .system("You are a helpful assistant.")
)


@cycls.agent(image=image, web=web)
async def {name}(context):
    async for ev in llm.run(context=context):
        yield cycls.to_ui(ev)
'''


def cmd_init(args):
    name = args.name or "my_agent"
    path = Path(f"{name}.py")
    if path.exists():
        sys.exit(f"Error: {path} already exists.")
    path.write_text(_STARTER_TEMPLATE.format(name=name))
    print(f"Created {path}")
    print()
    print("Next steps:")
    print(f"  cycls run {path}       # run locally in Docker")
    print(f"  cycls deploy {path}    # deploy to production")


def cmd_version(args):
    try:
        from importlib.metadata import version
        print(f"cycls {version('cycls')}")
    except Exception:
        print("cycls (development)")


# ---- Entry point ----

def main():
    parser = argparse.ArgumentParser(prog="cycls", description="Cycls — the deep-stack AI SDK")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", allow_abbrev=False,
                       help="Dev loop: rerun on save (local Docker; --remote for cloud)")
    p.add_argument("file", help="Path to agent file (file.py or file.py::name)")
    p.add_argument("--remote", action="store_true",
                   help="Run the loop in the cloud (f.remote / app.remote)")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("deploy", help="Deploy an agent to production")
    p.add_argument("file", help="Path to agent file (file.py or file.py::name)")
    p.set_defaults(func=cmd_deploy)

    p = sub.add_parser("shell", help="Open an interactive shell inside the built image")
    p.add_argument("file", help="Path to agent file (file.py or file.py::name)")
    p.set_defaults(func=cmd_shell)

    p = sub.add_parser("ls", help="List deployed agents")
    p.set_defaults(func=cmd_ls)

    p = sub.add_parser("rm", help="Delete a deployed agent")
    p.add_argument("name", help="Agent name")
    p.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")
    p.set_defaults(func=cmd_rm)

    p = sub.add_parser("logs", help="Fetch logs from a deployed agent")
    p.add_argument("name", help="Agent name")
    p.add_argument("-f", "--follow", action="store_true", help="Tail logs (poll every 2s)")
    p.add_argument("-q", "--query", default=None,
                   help='Cloud filter expression, e.g. \'jsonPayload.kind="fatal"\'')
    p.add_argument("-s", "--since", default=None,
                   help="Time window: 30m, 24h, 7d. Translated to an absolute timestamp filter.")
    p.set_defaults(func=cmd_logs)

    p = sub.add_parser("cost", help="Show spend on a deployed agent")
    p.add_argument("name", help="Agent name")
    p.add_argument("-s", "--since", default=None, help="Time window: 30m, 24h, 7d (default: 24h)")
    p.add_argument("-m", "--month", nargs="?", const=True, default=None, metavar="YYYY-MM",
                   help="Calendar month window (no value = current month). Mutually exclusive with --since.")
    p.add_argument("-b", "--by", choices=["user", "chat", "model"], help="Group results by this dimension")
    p.set_defaults(func=cmd_cost)

    p = sub.add_parser("sql", help="Run SQL against your deployment data in cycls cloud")
    p.add_argument("query", nargs="?", help="SQL query over `logs` and `billing` tables (omit to read from -f FILE or stdin; use `-` to force stdin)")
    p.add_argument("-f", "--file", default=None, help="Read the query from a file")
    p.add_argument("--format", choices=["table", "json", "csv"], default=None,
                   help="Output format (default: table on a TTY, json when piped)")
    p.add_argument("--json", action="store_true", help="Shortcut for --format json")
    p.set_defaults(func=cmd_sql)

    p = sub.add_parser("init", help="Scaffold a starter agent file")
    p.add_argument("name", nargs="?", help="Agent name (default: my_agent)")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("version", help="Print cycls version")
    p.set_defaults(func=cmd_version)

    args, extra = parser.parse_known_args()
    if args.command == "run":
        args.args = extra
    elif extra:
        parser.error(f"unrecognized arguments: {' '.join(extra)}")
    args.func(args)


if __name__ == "__main__":
    main()
