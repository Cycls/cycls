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


def cmd_logs(args):
    cursor = None
    while True:
        body = {"deployment_name": args.name, "limit": 100}
        if cursor:
            body["since"] = cursor
        data = _api("POST", "/v1/deployment/logs", json=body).json()
        for log in data.get("logs", []):
            ts = log.get("timestamp", "")
            sev = log.get("severity", "INFO")
            msg = log.get("message", "")
            print(f"{ts}  [{sev}]  {msg}")
        cursor = data.get("cursor")
        if not args.follow:
            return
        time.sleep(2)


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
    async for msg in llm.run(context=context):
        yield msg
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
    p.set_defaults(func=cmd_logs)

    p = sub.add_parser("init", help="Scaffold a starter agent file")
    p.add_argument("name", nargs="?", help="Agent name (default: my_agent)")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("version", help="Print cycls version")
    p.set_defaults(func=cmd_version)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
