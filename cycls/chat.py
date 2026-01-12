#!/usr/bin/env python3
"""cycls chat - Claude Code style CLI for cycls agents"""

import json, os, re, sys
import httpx

RESET, BOLD, DIM = "\033[0m", "\033[1m", "\033[2m"
BLUE, GREEN, YELLOW, RED = "\033[34m", "\033[32m", "\033[33m", "\033[31m"
CALLOUTS = {"success": ("✓", GREEN), "warning": ("⚠", YELLOW), "info": ("ℹ", BLUE), "error": ("✗", RED)}

separator = lambda: f"{DIM}{'─' * min(os.get_terminal_size().columns if sys.stdout.isatty() else 80, 80)}{RESET}"
markdown = lambda text: re.sub(r"\*\*(.+?)\*\*", f"{BOLD}\\1{RESET}", text)
header = lambda title, meta, color=GREEN, dim=False: print(f"{color}●{RESET} {BOLD}{title}{RESET}\n  ⎿  {meta}{DIM if dim else ''}", flush=True)


def table(headers, rows):
    if not headers: return
    widths = [max(len(str(h)), *(len(str(r[i])) for r in rows if i < len(r))) for i, h in enumerate(headers)]
    line = lambda left, mid, right: left + mid.join("─" * (w + 2) for w in widths) + right
    row = lambda cells, bold=False: "│" + "│".join(f" {BOLD if bold else ''}{str(cells[i] if i < len(cells) else '').ljust(widths[i])}{RESET if bold else ''} " for i in range(len(widths))) + "│"
    print(f"{line('┌', '┬', '┐')}\n{row(headers, True)}\n{line('├', '┼', '┤')}")
    for r in rows: print(row(r))
    print(line("└", "┴", "┘"))


def chat(url):
    messages, endpoint = [], f"{url.rstrip('/')}/chat/cycls"
    print(f"\n{BOLD}cycls{RESET} {DIM}|{RESET} {url}\n")

    while True:
        try:
            print(separator())
            user_input = input(f"{BOLD}{BLUE}❯{RESET} ").strip()
            print(separator())

            if not user_input: continue
            if user_input in ("/q", "exit", "quit"): break
            if user_input == "/c": messages, _ = [], print(f"{GREEN}⏺ Cleared{RESET}"); continue

            messages.append({"role": "user", "content": user_input})
            block, tbl = None, ([], [])

            def close():
                nonlocal block, tbl
                if block == "thinking": print(RESET)
                if block == "text": print()
                if block == "table" and tbl[0]: table(*tbl); tbl = ([], [])
                if block: print()
                block = None

            with httpx.stream("POST", endpoint, json={"messages": messages}, timeout=None) as response:
                for line in response.iter_lines():
                    if not line.startswith("data: ") or line == "data: [DONE]": continue
                    data = json.loads(line[6:])
                    type = data.get("type")

                    if type is None:
                        print(markdown(data if isinstance(data, str) else data.get("text", "")), end="", flush=True); continue

                    if type != block: close()

                    if type in ("thinking", "text"):
                        if block != type: header(type.capitalize(), "Live", dim=(type == "thinking")); block = type
                        print((markdown if type == "text" else str)(data.get(type, "")), end="", flush=True)
                    elif type == "code":
                        code = data.get("code", ""); header(f"Code({data.get('language', '')})", f"{code.count(chr(10))+1} lines"); print(code, flush=True); block = type
                    elif type == "status":
                        print(f"{DIM}[{data.get('status', '')}]{RESET} ", end="", flush=True)
                    elif type == "table":
                        if "headers" in data:
                            if tbl[0]: table(*tbl)
                            header("Table", f"{len(data['headers'])} cols"); tbl, block = (data["headers"], []), type
                        elif "row" in data: tbl[1].append(data["row"])
                    elif type == "callout":
                        style = data.get("style", "info"); icon, color = CALLOUTS.get(style, ("•", RESET))
                        header(style.capitalize(), f"{icon} {data.get('callout', '')}", color=color); block = type
                    elif type == "image":
                        header("Image", data.get("src", "")); block = type

            close()

        except KeyboardInterrupt: print()
        except EOFError: break
        except (httpx.ReadError, httpx.ConnectError) as e: print(f"{RED}⏺ Connection error: {e}{RESET}"); messages and messages.pop()


def main():
    if len(sys.argv) < 2:
        print("Usage: cycls chat <url|port>")
        sys.exit(1)
    arg = sys.argv[1]
    if arg.isdigit():
        port = int(arg)
        if not (1 <= port <= 65535):
            print(f"Error: Invalid port {port}. Must be between 1 and 65535.")
            sys.exit(1)
        url = f"http://localhost:{port}"
    else:
        url = arg
    chat(url)


if __name__ == "__main__":
    main()
