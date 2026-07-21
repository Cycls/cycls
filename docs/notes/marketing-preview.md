# Cycls — Marketing Preview

**Status**: Draft — write-up of the category, taglines, and launch copy for `cycls 1.0`
**Audience**: Cycls team (internal) + prep for launch (external)
**Related**: RFC 001 (primitives API), RFC 002 (data primitives)

---

## Category

**Cycls is the deep-stack AI SDK.**

Where most agent frameworks own one layer — the LLM loop, the deployment, the UI — Cycls owns every layer. Runtime, interface, intelligence, and state are all first-class composable Python primitives. One SDK, one mental model, one file.

---

## Hero

> **Cycls**
> **The deep-stack AI SDK for Python.**
>
> Agents as code. Every layer of your agent as a composable Python primitive. From infrastructure to intent, in one file.

```python
image = cycls.Image().pip("anthropic").volume("/workspace")
web   = cycls.Web().auth(True).title("Super")
llm   = cycls.LLM().model("claude-sonnet-4-6").system("You are Cycls.")

@cycls.agent(image=image, web=web, llm=llm)
async def super(context):
    async for call in context:
        ...
```

```bash
cycls deploy super.py
```

---

## What is deep-stack?

**Deep-stack** is the idea that every layer of an AI agent — runtime, interface, intelligence, state — should be a first-class Python primitive, composable with every other layer, with zero handoff between frameworks.

One SDK spans every layer of the agent stack. You never leave Python to write a Dockerfile. You never leave your agent file to configure auth. You never leave the same mental model to add persistent storage.

Other frameworks own one layer. **Cycls covers them all.**

---

## The primitives

**Cycls is seven composable primitives, three decorators, and one CLI.** That's the whole SDK.

```
Code primitives (declare once, reuse anywhere):
  cycls.Image   — runtime environment + resources
  cycls.Web     — UI, auth, branding, billing
  cycls.LLM     — model, system prompt, tools, runtime config

Data primitives (named, shareable, lifecycle-independent):
  cycls.Volume  — persistent files (cloud-backed, filesystem-mounted)
  cycls.Dict    — key-value store (future)
  cycls.Queue   — FIFO messaging (future)
  cycls.Secret  — encrypted credentials (future)

Decorators (compose primitives into deployable units):
  @cycls.function(image=)                    — pure compute
  @cycls.app(image=, web=)                   — chat service, you own the loop
  @cycls.agent(image=, web=, llm=)           — chat service, managed loop

CLI:
  cycls run file.py                           — local Docker, hot reload
  cycls deploy file.py                        — production
```

Every primitive names a real layer of your agent. Every primitive is composable with every other. Every primitive ships deployed, not as a local library.

---

## Deep-stack, explained

Today's AI agent stack forces you to stitch together five tools:

- A **Dockerfile** for runtime
- A **frontend framework** for the UI
- A **backend framework** for HTTP and auth
- An **agent library** for the LLM loop
- A **storage service** for state

Each tool has its own mental model, its own deployment story, its own failure modes. You spend half your time writing glue between them.

**Cycls collapses them into one SDK.** The `Image` is your Dockerfile. The `Web` is your frontend + auth + billing. The `@agent` decorator is your loop. The `Volume` is your storage. It's all Python, it's all composable, it all deploys with one command.

That's what we mean by deep-stack: **every layer, first-class, same framework**.

---

## Agents as code

**Cycls agents are code, not configuration.** Every layer of your agent is a Python object you can import, test, and compose. No YAML. No Docker compose files. No Terraform. No JSON configs. No separate infrastructure repo.

```python
# The whole stack, one file, valid Python.
image = cycls.Image().pip("openai").apt("poppler-utils")
web   = cycls.Web().auth(cycls.JWT(...))
llm   = cycls.LLM().model("claude-sonnet-4-6").system("...")
kb    = cycls.Volume("team-knowledge-base")

@cycls.agent(image=image, web=web, llm=llm, volumes={"/kb": kb})
async def super(context):
    async for call in context:
        ...
```

That's the whole agent. Runtime, interface, intelligence, state. Deployable with `cycls deploy super.py`.

---

## Go deep at any layer

Start at the highest level with one-line defaults:

```python
@cycls.agent(
    image=cycls.Image.agent(),
    web=cycls.Web().auth(True),
    llm=cycls.LLM().model("claude-sonnet-4-6"),
)
async def my_agent(context):
    async for call in context:
        pass
```

Drop down to any layer when you need to:

```python
# Custom Docker build step
image = cycls.Image().pip("custom").apt("custom").run("custom shell script")

# Custom FastAPI route
@my_agent.server.api_route("/webhook", methods=["POST"])
async def webhook(request, user = Depends(my_agent.auth)):
    ...

# Custom auth provider (WorkOS, Auth0, Okta, Firebase, anything OIDC)
web = cycls.Web().auth(cycls.JWT(jwks_url="...", issuer="..."))

# Custom LLM loop entirely — bypass the managed agent loop
@cycls.app(image=image, web=web)
async def my_chat(context):
    async for chunk in my_own_llm_pipeline(context.messages):
        yield chunk
```

**One SDK, any layer, any depth.** Same framework whether you're writing a Dockerfile line or a system prompt.

---

## The comparison

|  | Cycls | Modal | LangChain | OpenAI Agents | Claude Agent SDK | Vercel AI SDK |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Python-native | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Runtime primitive (Image) | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Interface primitive (Web/UI) | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |
| LLM primitive | ✅ | ❌ | Partial | ✅ | ✅ | ✅ |
| Data primitives (Volume, etc.) | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Managed agent loop | ✅ | ❌ | ✅ | ✅ | ✅ | Partial |
| Multi-LLM | ✅ | N/A | ✅ | ❌ | ❌ | ✅ |
| **Deep-stack (every row above)** | **✅** | ❌ | ❌ | ❌ | ❌ | ❌ |

Other frameworks own one or two layers. **Cycls is the only SDK that covers every layer.** That's the deep-stack claim, stated as a checklist.

---

## Launch copy

### Blog post titles

> **"Introducing Cycls — the deep-stack AI SDK"**
> *Subtitle: Agents as code. Seven composable primitives, three decorators, one CLI. From infrastructure to intent, in one Python file.*

> **"Why we built Cycls deep-stack"**
> *Subtitle: Every layer of an AI agent should be a first-class Python primitive. Here's how one SDK covers runtime, interface, intelligence, and state.*

> **"Agents as code: the seven primitives of Cycls 1.0"**

### HN pitch

> **Show HN: Cycls — the deep-stack AI SDK**
>
> *Agents as code for Python. Seven composable primitives cover runtime, interface, intelligence, and state. Three decorators compose them into deployable units. Start with one-line defaults; drop down to custom Dockerfiles, custom FastAPI routes, or your own LLM loop when you need to. Same framework at every layer.*

### Tweet

> Shipping Cycls 1.0 — the deep-stack AI SDK.
>
> Runtime. Interface. Intelligence. State. Every layer of your agent is a Python primitive. Compose with three decorators, deploy with one command.
>
> From infrastructure to intent, in one file. 🧵

### Elevator pitch

> "Cycls is the deep-stack AI SDK for Python. Most agent frameworks own one layer — the LLM loop, or the deployment, or the UI. Cycls covers every layer. Every layer of your agent is a composable Python primitive: runtime, interface, intelligence, state. You write an agent as code in one file, you deploy it with one command, and you can drop down to any layer when you need to customize. Same framework, any depth."

### Category positioning statement

> **Cycls is to agent frameworks what Modal is to serverless compute.**
>
> A deep-stack SDK that treats every layer as a first-class primitive. Python-native, cloud-deployed, composable end-to-end. Where other frameworks stop at one layer — LangChain at the loop, Modal at compute, Vercel at the UI — Cycls covers the whole agent surface. Seven primitives, three decorators, one CLI.

---

## Docs intro

> **What is Cycls?**
>
> Cycls is the deep-stack AI SDK for Python. It's a framework for building AI agents where every layer of the stack — runtime, interface, intelligence, and state — is a composable Python primitive.
>
> You declare primitives, compose them with decorators, and deploy with a single command. Agents as code.
>
> Start at the highest level with sensible defaults. Drop down to custom Docker builds, custom FastAPI routes, custom auth providers, or your own agent loop when you need to. Same framework, any depth.

---

## Section headings for the public docs

- **"What is deep-stack?"** — philosophy page explaining the category
- **"The seven primitives"** — one page per primitive (Image, Web, LLM, Volume, Dict, Queue, Secret)
- **"The three decorators"** — how primitives compose into deployable units
- **"Going deep at every layer"** — the progressive disclosure page
- **"From infrastructure to intent"** — the end-to-end tutorial
- **"Cycls vs other frameworks"** — comparison pages (LangChain, Modal, OpenAI Agents SDK, Claude Agent SDK, Vercel AI SDK)

Every section leans on the deep-stack framing. The category word does the positioning work; the substance (primitives, decorators, CLI) delivers on the promise.

---

## Positioning stack (one-page summary)

| Element | Phrase |
|---|---|
| **Category** | Deep-stack AI SDK |
| **Method** | Agents as code |
| **Claim** | Every layer. Any depth. |
| **Substance** | Seven composable primitives, three decorators, one CLI |
| **Range** | From infrastructure to intent, in one Python file |
| **Anchors** | *"Terraform for agents. Modal for AI. Go as deep as you need."* |

---

## Messaging discipline

**Do say**:
- "Deep-stack AI SDK"
- "Every layer as a composable primitive"
- "From infrastructure to intent"
- "Agents as code"
- "One SDK, any layer, any depth"
- "Go deep at any layer"
- "Cycls covers every layer"
- "Seven primitives, three decorators, one CLI"

**Don't say**:
- "Full-stack" (generic, frontend-coded connotation)
- "All-in-one" (marketing fluff)
- "Platform" without qualifying as SDK first
- "Framework" alone (too vague; use "deep-stack AI SDK" or "SDK")
- "AI operating system" (overreach)

**Rule of thumb**: *Deep-stack is the billboard. The primitives are the substance. Every sentence should deliver one or the other.*
