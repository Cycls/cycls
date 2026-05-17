"""cycls CLI — run, deploy, list, delete, logs, and scaffold agents."""
import argparse
import importlib.util
import os
import sys
import time
from pathlib import Path


# ---- Module loading ----

def _load_target(path_spec):
    """Import a file and return the first @cycls.function/app/agent instance.
    `path_spec` is 'file.py' or 'file.py::name' for an explicit target."""
    if "::" in path_spec:
        path_str, target = path_spec.split("::", 1)
    else:
        path_str, target = path_spec, None

    path = Path(path_str).resolve()
    if not path.exists():
        sys.exit(f"Error: {path} not found")

    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    spec.loader.exec_module(module)

    from cycls.function import Function
    from cycls.app import App

    if target:
        obj = getattr(module, target, None)
        if obj is None:
            sys.exit(f"Error: target '{target}' not found in {path}")
        return obj

    for _, obj in module.__dict__.items():
        if isinstance(obj, (Function, App)):
            return obj

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
    resp = httpx.request(
        method, f"{base_url}{path}",
        headers={"X-API-Key": api_key},
        timeout=30,
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

def cmd_run(args):
    instance = _load_target(args.file)
    instance._source_file = Path(args.file).resolve()
    if hasattr(instance, "local"):
        instance.local()
    else:
        instance.run()


def cmd_deploy(args):
    instance = _load_target(args.file)
    instance.deploy()


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
    """'30m' / '24h' / '7d' → absolute RFC-3339 UTC timestamp N units ago.
    Cloud Logging timestamp comparisons need absolute values."""
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


def cmd_cost(args):
    """Aggregate `level=usage` entries in Cloud Logging — total or grouped
    by user / chat / model. Pulls via /v1/deployment/logs, sums locally."""
    import json
    since = args.since or "24h"
    query = _join_query('jsonPayload.level="usage"', f'timestamp >= "{_parse_since(since)}"')
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
        print(f"No usage in last {since}.")
        return

    total = sum(float(e.get("cost", 0)) for e in entries)
    if not args.by:
        print(f"{args.name}  ${total:.6f}  ({len(entries)} turns, {since})")
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

    p = sub.add_parser("run", help="Run an agent locally in Docker")
    p.add_argument("file", help="Path to agent file (file.py or file.py::name)")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("deploy", help="Deploy an agent to production")
    p.add_argument("file", help="Path to agent file (file.py or file.py::name)")
    p.set_defaults(func=cmd_deploy)

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
                   help='GCP Cloud Logging filter, e.g. \'jsonPayload.kind="fatal"\'')
    p.add_argument("-s", "--since", default=None,
                   help="Time window: 30m, 24h, 7d. Translated to an absolute timestamp filter.")
    p.set_defaults(func=cmd_logs)

    p = sub.add_parser("cost", help="Show spend on a deployed agent")
    p.add_argument("name", help="Agent name")
    p.add_argument("-s", "--since", default=None, help="Time window: 30m, 24h, 7d (default: 24h)")
    p.add_argument("-b", "--by", choices=["user", "chat", "model"], help="Group results by this dimension")
    p.set_defaults(func=cmd_cost)

    p = sub.add_parser("init", help="Scaffold a starter agent file")
    p.add_argument("name", nargs="?", help="Agent name (default: my_agent)")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("version", help="Print cycls version")
    p.set_defaults(func=cmd_version)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
