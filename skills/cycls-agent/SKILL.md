---
name: cycls-agent
description: >-
  Creates and ships a Cycls Python chat agent, FastAPI app, or containerized
  function. Asks for the missing choices, writes the file, splits machine
  keys from container keys, runs it in local Docker, or deploys it to a
  cycls.ai URL. Use when the user invokes /cycls-agent or $cycls-agent, asks
  to make, run, or deploy a Cycls agent, app, or function, or pastes this
  file into ChatGPT, Claude, or another chat.
disable-model-invocation: true
---

# Cycls agent

Ship one Cycls target. Paste this file into a Claude Project, a ChatGPT GPT, or a new chat. This skill's directory is reference material, not the project.

The current API is fluent builders (`Image`, `Web`, `LLM`, `Volume`) and the `cycls` CLI. If a page shows `app.deploy()`, `pip=[...]` on a decorator, or `copy=[".env"]`, it is stale. Ignore it.

## Where you are running

Use machine mode when you can write files and run commands in their project. Use chat mode when you have no shell on their machine. ChatGPT, Claude.ai, and other chatbots are chat mode.

Machine mode runs the steps below itself.

Chat mode still finishes the task. Ask the questions here, then send one handoff:

1. `mkdir <slug> && cd <slug>`
2. Every file in full. Each file gets its own fenced block, with the filename on the line above the fence. Include `.gitignore`, `.env`, and `.providers.env`. The env files contain the variable name and an empty value.
3. The commands, in order, in one block. Include only the command for this step.

Then stop. Wait for terminal output or an explicit deploy yes. Ask them to delete any line that contains a key before pasting. On a failure, reply with the corrected file in full and the command to run again. On a line that contains `[DONE]`, repeat the `https://` URL from that paste.

Do not install Cycls or start Docker in your own sandbox. The user runs those commands on their computer.

If you can open the docs, fetch them before writing code and follow them when they disagree with this file. If you cannot, this file is the procedure.

- https://docs.cycls.com/llms.txt
- https://docs.cycls.com/get-started/quickstart.md
- https://docs.cycls.com/ship/cli.md

Fetch another page from the index only when this skill sends you there.

## 1. Classify

| They want | Decorator | Then |
| --- | --- | --- |
| A chat product (default) | `@cycls.agent` | Stay in this skill |
| An HTTP service or custom frontend | `@cycls.app` | Fetch https://docs.cycls.com/build/apps.md and https://docs.cycls.com/guides/fastapi-app.md |
| A job, endpoint, or cron | `@cycls.function` | Fetch https://docs.cycls.com/build/functions.md |

An agent stays on this page. An app or a function takes its decorator from those pages, then uses the key split, the import rule, and the deploy gate below.

## 2. Ask once

Use what the user already said. Ask only for the gaps, in one message, with a default they can accept. Stop until they answer.

1. What it does. One paragraph. This becomes `.system()`.
2. Public name. Lowercase slug. The function is the slug with hyphens turned into underscores. Set `name=` to the slug they will type in the URL.
3. Model. Default `anthropic/claude-sonnet-4-6`. Any other model is `vendor/model`.
4. Tools. Default none. Add only what the job needs.
5. Sign-in. Default `cycls.Clerk()` for a chat on the web. Anonymous only if they ask.
6. Where it runs. Local Docker, a public URL, or local first and deploy after it works. Default local first.
7. Extra pip or apt packages. Default none.

Do not ask them to paste a key into the chat.

Defaults when they say to decide:

- Tools that answer from the model only: no tools.
- Needs current public info: `WebSearch`.
- Writes a file the user should see: `Editor` and `Canvas`.
- Runs shell: `Bash` plus `.sandbox(network=False)`. Add network only if they need `curl`, `pip`, or `git` from the sandbox.
- Remembers user preferences: `DataBase`.
- `Browser` and `Apps` stay off unless they already have that service's environment variables. Fetch https://docs.cycls.com/agents/tools.md before enabling either.
- A custom tool only if they described a specific action. Fetch https://docs.cycls.com/guides/custom-tool.md and use its handler shape.

## 3. Rules

- Python 3.10 or newer. The container matches the major.minor of the interpreter that runs the CLI.
- Install the SDK in that same environment: `python3 -m pip install -U cycls`. Then run `cycls version`. Do not add `cycls` to `.pip()`.
- `cycls` imports the file. Never call `.run()`, `.remote()`, `.local()`, or `.deploy()` at import time.
- An agent mounts a volume at `/workspace`. The volume name is `<slug>-chats`.
- Deleting a deployment does not delete the volume. Do not run `cycls rm` or `cycls volume delete` unless they explicitly ask.
- `.env` stays on the machine. It holds `CYCLS_API_KEY`. Get the key at https://cloud.cycls.com.
- `.providers.env` is copied into the image as `.env`. It holds the model key and any handler key. Never put `CYCLS_API_KEY` there unless they explicitly need this deployment to call another Cycls deployment.
- Do not read either env file. Do not print their contents, `env`, or a command that echoes a key.
- `cycls run <file>` is the local agent loop and needs Docker. `cycls run <file> --remote` is not an agent path. It exits for agents. A public agent URL is `cycls deploy`.
- `cycls deploy` builds in the cloud and does not need Docker. Redeploying the same `name=` updates that deployment in place.
- Source archive limit is 100 MiB. Large files go on a volume with `cycls volume put`, not `.copy()`.
- Leave quota, billing, connectors, and MCP out unless they asked. Prices for `cycls cost` come from `.price(...)` in USD per million tokens. Do not invent prices.

## 4. Write the agent

In machine mode, create the directory if they named a new one. If `<function>.py` already exists, edit it. Do not run `cycls init` over their file. In chat mode, put these files in the handoff. Do not say they are already on disk.

Append any missing lines to `.gitignore`:

```
.env
.providers.env
.venv/
__pycache__/
```

Create a missing env file with the variable name and an empty value. Never overwrite a file that already has values.

`.env`

```
CYCLS_API_KEY=
```

`.providers.env` gets the key that model reads:

| Model prefix | Variable |
| --- | --- |
| `anthropic/` | `ANTHROPIC_API_KEY` |
| `openai/` | `OPENAI_API_KEY` |
| anything else | the vendor key, passed with `.api_key(os.environ["THAT_KEY"])` and `.base_url(...)` |

`WebSearch` on a non-Anthropic model also needs `BRAVE_API_KEY` in `.providers.env`. On Anthropic it falls back to native search when that key is absent. Fetch https://docs.cycls.com/agents/models.md before using a non-Anthropic model.

```python
import cycls

image = cycls.Image().copy(".providers.env", ".env")
chats = cycls.Volume("market-notes-chats")

web = (
    cycls.Web()
    .auth(cycls.Clerk())
    .title("Market Notes")
    .brand(name="Market Notes", description="One sentence they will recognize.")
)

llm = (
    cycls.LLM()
    .model("anthropic/claude-sonnet-4-6")
    .system("The paragraph they agreed to.")
)

@cycls.agent(name="market-notes", image=image, web=web, volumes={"/workspace": chats})
async def market_notes(context):
    async for ev in llm.run(context=context):
        yield ev
```

Adapt that file. Do not leave this sample's names in place.

- Omit `.copy(...)` when the container needs no secrets. A missing source file fails the build.
- Extra packages go on the image: `.pip("httpx")`, `.apt("ffmpeg")`.
- A helper imported by the agent is bundled with `.copy("helpers.py")`. Copied modules land on `/app`.
- Anonymous chat: drop `.auth(...)`. That also drops per-user files, share links, and workspaces.
- Tools go on the builder, for example `.allowed_tools(["WebSearch", "Editor", "Canvas"])`.
- Bash without network: `.allowed_tools(["Bash"]).sandbox(network=False)`.
- Their own Clerk or OIDC tenant: fetch https://docs.cycls.com/web/auth.md and use `cycls.Clerk(...)` or `cycls.JWT(...)`.

A custom tool, only when requested:

```python
TOOLS = [{
    "name": "create_ticket",
    "description": "Open a ticket for the signed-in user.",
    "inputSchema": {
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "required": ["title"],
    },
}]

async def create_ticket(args, ctx):
    return f"Created for {ctx.user.id}: {args['title']}"

llm = llm.tools(TOOLS).on("create_ticket", create_ticket)
```

Reserved tool names: `skill`, `find_tools`, `bash`, `read`, `edit`, `database`. A handler key lives in `.providers.env`, not in the source.

## 5. Check keys

Run this and change `PROVIDER_KEY` to the variable you required. In chat mode, put the script in the handoff and wait. The user pastes the three status words, not the env files.

```bash
python3 - <<'PY'
from pathlib import Path

def status(path, key):
    file = Path(path)
    if not file.is_file():
        return "missing-file"
    for raw in file.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == key and value.strip():
            return "set"
    return "empty"

print("deploy-key", status(".env", "CYCLS_API_KEY"))
print("provider-key", status(".providers.env", "PROVIDER_KEY"))
print("deploy-key-in-image", status(".providers.env", "CYCLS_API_KEY"))
PY
```

`deploy-key-in-image` must be `missing-file` or `empty`. If it is `set`, remove that line unless they explicitly need cross-deployment calls.

A local run requires `provider-key` to be `set` when the model or a tool needs one. Deploy, `cycls ls`, and `cycls logs` also require `deploy-key` to be `set`. An empty deploy key does not block a local run. For every required status that is `missing-file` or `empty`, name the file and the variable, then wait. Do not continue that step.

## 6. Run locally

Skip this when they asked to deploy only.

Confirm Docker with `docker info`. If it is not running, ask them to start Docker, or switch to deploy. Do not invent a remote agent loop. In chat mode, the handoff command is `cycls run <file>.py`. Tell them the first build takes one to two minutes, the terminal stays open, and the page is `http://localhost:8080`.

```bash
cycls run market_notes.py
```

The first build takes one to two minutes. Leave it running and watch until it is serving `http://localhost:8080` or the build prints an error. Fix the error and run again. Tell them the local URL. Saving the file reloads.

## 7. Deploy

Do this only after an explicit yes in this conversation. Show this summary, then stop. In chat mode the summary contains no deploy command. After they say yes, reply with only the deploy command. When they paste `[DONE]`, give them the URL from that paste.

```
Deploy <slug>?
URL: https://<slug>.cycls.ai
Model: <vendor/model>
Tools: <list or none>
Auth: <Clerk, JWT, or anonymous>
Volume: <slug>-chats
The provider key in .providers.env will be inside the image.
cycls deploy <file>.py
```

After they agree:

```bash
cycls deploy market_notes.py
```

Several decorated objects in one file: `cycls deploy market_notes.py::market-notes`.

On `[DONE]`, give them that exact URL. Then run `cycls ls`. Logs, only if they ask or a request failed:

```bash
cycls logs market-notes
```

A taken name belongs to another account when the error says so. Agree a new `name=` and deploy again. Keep the volume name if they want the old files. If `name=` is rejected as invalid, delete that argument, keep a lowercase function name, and use the URL the CLI prints.

## 8. When a command fails

| Failure | Fix |
| --- | --- |
| `cycls` not found | Install into the interpreter you are using, then use that environment's `cycls` |
| Docker daemon down | Start Docker, or deploy without a local run |
| `--remote` refused on an agent | `cycls run` or `cycls deploy` |
| Name unavailable | New `name=` |
| Missing `/workspace` volume | Add `volumes={"/workspace": cycls.Volume("<slug>-chats")}` |
| Model auth error inside the container | Provider key is empty or in `.env` instead of `.providers.env` |
| Import error for their module | `.copy()` that file |
| Archive too large | Remove the large file from `.copy()` and use `cycls volume put` |
| Build or runtime error this table does not name | Open the matching page from https://docs.cycls.com/llms.txt when you can, and follow it. In chat mode, send the corrected file in full |

Done in machine mode means the file is on disk, required keys report `set`, and they have a local URL, a deployed URL, or a stated reason the remaining step is waiting on them. Done in chat mode means they have the files and the next command, or the URL from output they pasted.
