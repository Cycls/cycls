<h3 align="center">
The Distribution SDK for AI Agents.
</h3>

<h4 align="center">
  <a href="https://cycls.com">Website</a> |
  <a href="https://docs.cycls.com">Docs</a>
</h4>

<h4 align="center">
  <a href="https://pypi.python.org/pypi/cycls"><img src="https://img.shields.io/pypi/v/cycls.svg?label=cycls+pypi&color=blueviolet" alt="cycls Python package on PyPi" /></a>
  <a href="https://blog.cycls.com"><img src="https://img.shields.io/badge/newsletter-blueviolet.svg?logo=substack&label=cycls" alt="Cycls newsletter" /></a>
  <a href="https://x.com/cyclsai">
    <img src="https://img.shields.io/twitter/follow/CyclsAI" alt="Cycls Twitter" />
  </a>
</h4>


# Cycls 🚲

`cycls` is a zero-config framework for building and publishing AI agents. With a single decorator and one command, you can deploy your code as a web application complete with a front-end UI and an OpenAI-compatible API endpoint.

### Design Philosophy
`cycls` is an anti-framework. We treat the boilerplate, config files, and infrastructure that surround modern applications as a bug to be eliminated. A developer's focus is the most valuable resource, and context-switching is its greatest enemy.

Our zero-config approach makes your Python script the single source of truth for the entire application. When your code is all you need, you stay focused, iterate faster, and ship with confidence.

This philosophy has a powerful side-effect: it makes development genuinely iterative. The self-contained nature of an agent encourages you to 'build in cycles'—starting simple and adding complexity without penalty. This same simplicity also makes `cycls` an ideal target for code generation. Because the entire application can be expressed in one file, LLMs can write, modify, and reason about `cycls` agents far more effectively than with traditional frameworks. It's a seamless interface for both human and machine.


## Key Features

* ✨ **Zero-Config Deployment:** No YAML or Dockerfiles. `cycls` infers your dependencies, and APIs directly from your Python code.
* 🚀 **One-Command Push to Cloud:** Go from local code to a globally scalable, serverless application with a single `agent.deploy()`.
* 💻 **Instant Local Testing:** Run `agent.local()` to spin up a local server with hot-reloading for rapid iteration and debugging.
* 🤖 **OpenAI-Compatible API:** Automatically serves a streaming `/chat/completions` endpoint.
* 🌐 **Automatic Web UI:** Get a clean, interactive front-end for your agent out of the box, with no front-end code required.
* 🔐 **Built-in Authentication:** Secure your agent for production with a simple `auth=True` flag that enables JWT-based authentication.
* 📦 **Declarative Dependencies:** Define all your `pip`, `apt`, or local file dependencies directly in Python.


## Installation

```bash
pip install cycls
```

## How to Use
### 1. Local Development: "Hello, World!"

Create a file main.py. This simple example creates an agent that streams back the message "hi".

```py
import cycls

# Initialize the agent
agent = cycls.Agent()

# Decorate your function to register it as an agent
@agent()
async def hello(context):
    yield "hi"

agent.local()
```

Run it from your terminal:

```bash
python main.py
```
This will start a local server. Open your browser to http://localhost:8080 to interact with your agent.

## 2. Cloud Deployment: An OpenAI-Powered Agent

This example creates a more advanced agent that calls the OpenAI API.  
**Note:** When deploying to the Cycls Cloud, you must pass your Cycls deployment key using the `api_key` argument.

```python
# deploy.py
import cycls

# Initialize the agent with dependencies and API keys
agent = cycls.Agent(
    pip=["openai"],
    keys=["ak-<token_id>", "as-<token_secret>"],
    api_key="cs-<your-cycls-api-key>"
)

# A helper function to call the LLM
async def llm(messages):
    # Import inside the function: 'openai' is only needed at runtime in the container.
    import openai
    client = openai.AsyncOpenAI(api_key="sk-...") # Your OpenAI key
    model = "gpt-4o"
    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=1.0,
        stream=True
    )
    # Yield the content from the streaming response
    async def event_stream():
        async for chunk in response:
            content = chunk.choices[0].delta.content
            if content:
                yield content
    return event_stream()

# Register the function as an agent named "cake" and enable auth
@agent("cake", auth=True)
async def cake_agent(context):
    # The context object contains the message history
    return await llm(context.messages)

# Deploy the agent to the cloud
agent.deploy(prod=True)
```

### Explanation

- `keys=[...]` secrets passed into the **agent container runtime**.
- `api_key="..."` the **Cycls Cloud deployment key** required for `prod=True`.

### License
This project is licensed under the MIT License.