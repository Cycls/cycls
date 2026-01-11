import sys
import json
import time
import threading
import httpx

# ANSI codes
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"
CLEAR_LINE = "\r\033[K"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
RED = "\033[31m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"

CALLOUT_STYLES = {
    "success": ("✓", GREEN),
    "warning": ("⚠", YELLOW),
    "info": ("ℹ", BLUE),
    "error": ("✗", RED),
}

def format_time(seconds):
    if seconds < 60:
        return f"{seconds:.1f}s"
    return f"{int(seconds // 60)}m {int(seconds % 60)}s"

def render_table(headers, rows):
    if not headers:
        return
    widths = [len(str(h)) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(str(cell)))

    top = "┌" + "┬".join("─" * (w + 2) for w in widths) + "┐"
    sep = "├" + "┼".join("─" * (w + 2) for w in widths) + "┤"
    bot = "└" + "┴".join("─" * (w + 2) for w in widths) + "┘"

    def fmt_row(cells, bold=False):
        parts = []
        for i, w in enumerate(widths):
            cell = str(cells[i]) if i < len(cells) else ""
            if bold:
                parts.append(f" {BOLD}{cell.ljust(w)}{RESET} ")
            else:
                parts.append(f" {cell.ljust(w)} ")
        return "│" + "│".join(parts) + "│"

    print(top)
    print(fmt_row(headers, bold=True))
    print(sep)
    for row in rows:
        print(fmt_row(row))
    print(bot)

class Spinner:
    def __init__(self):
        self.active = False
        self.thread = None
        self.frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def start(self):
        self.active = True
        def spin():
            i = 0
            while self.active:
                if not self.active:
                    break
                print(f"\r{MAGENTA}{self.frames[i % len(self.frames)]}{RESET} ", end="", flush=True)
                for _ in range(8):  # Check active more frequently
                    if not self.active:
                        break
                    time.sleep(0.01)
                i += 1
        self.thread = threading.Thread(target=spin, daemon=True)
        self.thread.start()

    def stop(self):
        self.active = False
        if self.thread:
            self.thread.join(timeout=0.2)
        print(f"{CLEAR_LINE}", end="", flush=True)

def chat(url):
    messages = []
    endpoint = f"{url.rstrip('/')}/chat/cycls"

    print(f"\n{MAGENTA}●{RESET} {BOLD}{url}{RESET}\n")

    while True:
        try:
            user_input = input(f"{CYAN}❯{RESET} ")
            if not user_input.strip():
                continue

            messages.append({"role": "user", "content": user_input})
            print()

            start_time = time.time()
            in_thinking = False
            table_headers = []
            table_rows = []

            with httpx.stream("POST", endpoint, json={"messages": messages}, timeout=None) as r:
                for line in r.iter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":

                        data = json.loads(line[6:])
                        msg_type = data.get("type")

                        # Handle plain string or missing type
                        if msg_type is None:
                            # Could be OpenAI format or plain text
                            if isinstance(data, str):
                                print(data, end="", flush=True)
                                continue
                            elif "choices" in data:
                                # OpenAI format
                                content = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                                if content:
                                    print(content, end="", flush=True)
                                continue
                            elif "text" in data:
                                print(data.get("text", ""), end="", flush=True)
                                continue
                            elif "content" in data:
                                print(data.get("content", ""), end="", flush=True)
                                continue
                            else:
                                # Debug: print raw data
                                print(f"[debug: {data}]", end="", flush=True)
                                continue

                        # Close thinking if switching
                        if msg_type != "thinking" and in_thinking:
                            print(f"</thinking>{RESET}\n", end="", flush=True)
                            in_thinking = False

                        # Flush table if switching
                        if msg_type != "table" and table_headers:
                            render_table(table_headers, table_rows)
                            table_headers = []
                            table_rows = []

                        if msg_type == "thinking":
                            if not in_thinking:
                                print(f"{DIM}<thinking>", end="", flush=True)
                                in_thinking = True
                            print(data.get("thinking", ""), end="", flush=True)

                        elif msg_type == "text":
                            print(data.get("text", ""), end="", flush=True)

                        elif msg_type == "code":
                            lang = data.get("language", "")
                            print(f"\n```{lang}\n{data.get('code', '')}\n```\n", end="", flush=True)

                        elif msg_type == "status":
                            print(f"{DIM}[{data.get('status', '')}]{RESET} ", end="", flush=True)

                        elif msg_type == "table":
                            if "headers" in data:
                                if table_headers:
                                    render_table(table_headers, table_rows)
                                table_headers = data["headers"]
                                table_rows = []
                            elif "row" in data:
                                table_rows.append(data["row"])

                        elif msg_type == "callout":
                            style = data.get("style", "info")
                            icon, color = CALLOUT_STYLES.get(style, ("•", RESET))
                            title = data.get("title", "")
                            text = data.get("callout", "")
                            if title:
                                print(f"\n{color}{icon} {BOLD}{title}{RESET}")
                                print(f"{color}  {text}{RESET}\n", end="", flush=True)
                            else:
                                print(f"\n{color}{icon} {text}{RESET}\n", end="", flush=True)

                        elif msg_type == "image":
                            print(f"{DIM}[image: {data.get('src', '')}]{RESET}", end="", flush=True)

            # Flush remaining
            if table_headers:
                render_table(table_headers, table_rows)
            if in_thinking:
                print(f"</thinking>{RESET}", end="", flush=True)

            elapsed = time.time() - start_time
            print(f"\n\n{DIM}✦ {format_time(elapsed)}{RESET}\n")

        except KeyboardInterrupt:
            continue
        except EOFError:
            print(f"{RESET}\n👋")
            break
        except (httpx.ReadError, httpx.ConnectError):
            print(f"{RESET}🔄 Reconnecting...", end="", flush=True)
            time.sleep(1)
            print(CLEAR_LINE, end="")
            if messages:
                messages.pop()

def main():
    if len(sys.argv) < 3 or sys.argv[1] != "chat":
        print("Usage: cycls chat <url>")
        sys.exit(1)
    chat(sys.argv[2])

if __name__ == "__main__":
    main()
