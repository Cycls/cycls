# Cycls Runtime

Run any Python function in an isolated container with full dependency control.

> **Source:** [`cycls/runtime.py`](../cycls/runtime.py) - The `Runtime` class handles Docker image generation, function serialization with cloudpickle, content-addressable caching, and container execution.

---

## Overview

The `@cycls.function` decorator transforms a Python function into a containerized, executable unit. Your function runs in Docker with its own Python environment, system packages, and files - completely isolated from your local machine.

```python
import cycls

@cycls.function(pip=["numpy", "pandas"])
def compute(x):
    import numpy as np
    return np.array(x).mean()

result = compute.run([1, 2, 3, 4, 5])
print(result)  # 3.0
```

---

## Examples

### Monte Carlo Simulation

```python
import cycls

@cycls.function(pip=["numpy", "pandas", "tabulate"])
def monte_carlo(num_points: int = 1000000):
    import numpy as np
    import pandas as pd

    # Generate random points
    points = np.random.rand(num_points, 2)
    distances = np.sqrt(points[:, 0]**2 + points[:, 1]**2)
    inside = np.sum(distances <= 1)

    # Estimate Pi
    pi_estimate = 4 * (inside / num_points)

    print(f"Points: {num_points}")
    print(f"Inside circle: {inside}")
    print(f"Pi estimate: {pi_estimate}")

    return pi_estimate

result = monte_carlo.run(num_points=100000)
print(f"Returned: {result}")
```

### Run a FastAPI Server

```python
import cycls

@cycls.function(pip=["fastapi", "uvicorn"])
def server(port):
    from fastapi import FastAPI
    import uvicorn

    app = FastAPI()

    @app.get("/")
    def root():
        return {"message": "Hello from container"}

    uvicorn.run(app, host="0.0.0.0", port=port)

server.run(port=8000)
```

### Jupyter Notebook

```python
import cycls
import os

@cycls.function(pip=["jupyter"])
def jupyter_notebook(port):
    command = (
        f"jupyter notebook --ip=0.0.0.0 --port={port} --allow-root "
        "--NotebookApp.token='' --NotebookApp.password=''"
    )
    print(f"Starting Jupyter Notebook server at http://localhost:{port}")
    os.system(command)

jupyter_notebook.run(port=8888)
```

### Marimo Notebook

```python
import cycls
import os

@cycls.function(pip=["marimo"])
def marimo_notebook(port):
    command = f"marimo edit --host 0.0.0.0 --port {port} --no-token"
    print(f"Starting Marimo notebook server at http://localhost:{port}")
    os.system(command)

marimo_notebook.run(port=8080)
```

> **More examples:** See [`examples/function/`](../examples/function/) for additional use cases including Monte Carlo simulations, ticker streams, and more.

---

## The Power of Arbitrary Functions

The `@cycls.function` interface is intentionally unopinionated. Any Python function can become a containerized workload:

- **Batch jobs** - Data processing, ML training, ETL pipelines
- **Long-running services** - Web servers, notebooks, daemons
- **System tasks** - Compile C code, run shell scripts, interact with hardware
- **Hybrid workloads** - Mix Python with `os.system()` calls to orchestrate anything

Because the function runs in a full Linux container with root access, you have complete control over the environment. Install system packages with `apt`, run arbitrary shell commands with `run_commands`, or execute processes at runtime with `os.system()`.

```python
# Compile and run C code
@cycls.function(apt=["gcc", "libc6-dev"])
def run_c_code():
    import subprocess
    with open("hello.c", "w") as f:
        f.write('#include <stdio.h>\nint main() { printf("Hello\\n"); return 0; }')
    subprocess.run(["gcc", "hello.c", "-o", "hello"], check=True)
    result = subprocess.run(["./hello"], capture_output=True, text=True)
    return result.stdout.strip()

run_c_code.run()  # "Hello"
```

The only constraint is Python's ability to serialize your function with cloudpickle. Beyond that, the container is yours.

---

## Decorator Options

```python
@cycls.function(
    pip=["numpy", "pandas"],           # Python packages
    apt=["ffmpeg"],                     # System packages
    run_commands=["curl ... | bash"],   # Shell commands during build
    copy=["./utils.py", "./data/"],     # Files to include
    python_version="3.11",              # Python version (default: current)
    name="my-function",                 # Container name (default: function name)
)
def my_function():
    ...
```

| Option | Description |
|--------|-------------|
| `pip` | Python packages installed via pip |
| `apt` | System packages installed via apt-get |
| `run_commands` | Shell commands executed during container build |
| `copy` | Files and directories bundled into the container |
| `python_version` | Python version for the container (defaults to your current version) |
| `name` | Name for the container image (defaults to function name) |

---

## Methods

The decorated function becomes a `Runtime` object with these methods:

### `.run(*args, **kwargs)`

Execute the function in a container and return the result.

```python
@cycls.function(pip=["numpy"])
def add(a, b):
    import numpy as np
    return np.add(a, b).tolist()

result = add.run([1, 2], [3, 4])  # [4, 6]
```

- Starts a gRPC server in the container (or reuses existing)
- Sends the function and arguments over gRPC
- Streams logs to stdout
- Returns the deserialized result

### `.stream(*args, **kwargs)`

Execute and yield streaming results from a generator function.

```python
@cycls.function()
def count(n):
    for i in range(n):
        yield i

for value in count.stream(5):
    print(value)  # 0, 1, 2, 3, 4
```

- Uses gRPC streaming for real-time results
- Each `yield` in the function sends a response immediately

### `.watch(*args, **kwargs)`

Run with file watching - automatically restarts on code changes.

```python
@cycls.function(pip=["fastapi", "uvicorn"])
def api(port):
    ...

api.watch(port=8000)  # Restarts when files change
```

### `.build(*args, **kwargs)`

Build a self-contained Docker image with the function baked in.

```python
@cycls.function(pip=["fastapi", "uvicorn"])
def api(port):
    ...

image_tag = api.build(port=8000)
# Returns: "cycls/api:deploy-abc123"
```

The resulting image runs standalone (no gRPC, no external dependencies):

```bash
docker run -p 8000:8000 cycls/api:deploy-abc123
```

### `.deploy(*args, **kwargs)`

Deploy the function to the Cycls cloud.

```python
import cycls
cycls.api_key = "YOUR_API_KEY"

@cycls.function(pip=["numpy"])
def compute(data):
    ...

url = compute.deploy(data=[1, 2, 3])
# Returns: "https://compute.cycls.ai"
```

---

## How It Works

Cycls uses two different execution modes optimized for their use cases:

| Mode | Method | Communication | Use Case |
|------|--------|---------------|----------|
| **Local Dev** | `.run()`, `.stream()` | gRPC | Fast iteration, streaming support |
| **Deploy** | `.build()`, `.deploy()` | Pickle + Entrypoint | Standalone images, no runtime deps |

### 1. Function Serialization

Your function is serialized using [cloudpickle](https://github.com/cloudpipe/cloudpickle), which captures:

- The function bytecode
- Closures and referenced variables
- Dynamically defined functions and lambdas

```python
multiplier = 10

@cycls.function()
def scale(x):
    return x * multiplier  # `multiplier` is captured

scale.run(5)  # 50
```

### 2. Content-Addressable Images

Cycls generates a deterministic image tag by hashing:

- Python version
- pip packages
- apt packages
- run_commands
- Contents of copied files

```
cycls/my-function:a1b2c3d4e5f6g7h8
                  └── hash of all dependencies
```

Same dependencies = same hash = cached image. Change a dependency, the hash changes, and a new image builds.

### 3. Local Development (gRPC)

For `.run()` and `.stream()`, Cycls uses gRPC for fast container communication:

```
┌─────────────────┐
│  Your Machine   │
│  ┌───────────┐  │
│  │  Client   │  │──────── gRPC ────────┐
│  └───────────┘  │                      │
└─────────────────┘                      ▼
                              ┌─────────────────┐
                              │    Container    │
                              │  ┌───────────┐  │
                              │  │gRPC Server│  │
                              │  └───────────┘  │
                              │       │         │
                              │       ▼         │
                              │  func(*args)    │
                              │       │         │
                              │       ▼         │
                              │    result       │
                              └────────┬────────┘
                                       │
                         ◀── gRPC ─────┘
```

**Benefits:**
- Container stays warm between calls
- Streaming results supported
- Fast iteration during development

### 4. Deploy Mode (Pickle + Entrypoint)

For `.build()` and `.deploy()`, Cycls bakes the function into a standalone image:

```dockerfile
FROM ghcr.io/cycls/base:python3.12
COPY function.pkl /app/function.pkl
COPY entrypoint.py /app/entrypoint.py
CMD ["python", "entrypoint.py"]
```

The entrypoint loads and executes the pickled function:

```python
import cloudpickle
with open("/app/function.pkl", "rb") as f:
    func, args, kwargs = cloudpickle.load(f)
func(*args, **kwargs)
```

**Benefits:**
- No gRPC dependencies (smaller images)
- Function + args baked in
- Runs anywhere Docker runs

---

## Caching

Cycls automatically caches Docker images based on their content hash.

**First run:**
```
🐳 Initializing Docker client...
🛠️  Building new base image: cycls/monte-carlo:a1b2c3d4
--- Docker Build Logs ---
...
✅ Base image built successfully
🚀 Running function 'monte-carlo' in container...
```

**Subsequent runs (same dependencies):**
```
🐳 Initializing Docker client...
✅ Found cached base image: cycls/monte-carlo:a1b2c3d4
🚀 Running function 'monte-carlo' in container...
```

### Auto-Cleanup

Old images are automatically cleaned up when you run a function. Cycls keeps:

- The current image (matching your dependencies)
- Any `deploy-*` tagged images (for deployment)

Everything else is pruned.

---

## Pre-built Base Images

To further reduce build times, cycls uses pre-built base images with common dependencies already installed. This reduces agent build time from ~60s to <5s.

### How It Works

1. **Base Image**: `ghcr.io/cycls/base:python3.12` includes pre-installed packages:
   - cloudpickle, cryptography, fastapi[standard], pydantic, pyjwt, uvicorn[standard], httpx

2. **Automatic Package Filtering**: The runtime filters out packages already in the base image. Only additional dependencies trigger a pip install step.

3. **Layer Caching**: Docker caches each layer. Since base dependencies rarely change, subsequent builds reuse cached layers instantly.

### GitHub Container Registry

Base images are hosted on GitHub Container Registry and automatically rebuilt when `images/` changes.

**Workflow triggers:**
- Push to `images/` directory on main branch
- Manual trigger via GitHub Actions UI

**Image tags:**
- `ghcr.io/cycls/base:python3.12` - Python 3.12 base image

### Custom Base Images

To use a different base image, pass `base_image` to the Runtime:

```python
from cycls.runtime import Runtime

runtime = Runtime(
    func=my_func,
    name="my-agent",
    base_image="my-registry/my-base:tag",
    pip_packages=["package"]  # All packages installed, no filtering
)
```

When using a custom base image, package filtering is disabled.

---

## Importing Local Modules

Use the `copy` parameter to include local Python files:

```python
# utils.py
def helper():
    return "I'm a helper"

# main.py
import cycls

@cycls.function(copy=["./utils.py"])
def my_function():
    from utils import helper
    return helper()

my_function.run()  # "I'm a helper"
```

Copy entire directories:

```python
@cycls.function(copy=["./my_package/"])
def my_function():
    from my_package import module
    ...
```

---

## Port Mapping

For long-running services, pass a `port` argument:

```python
@cycls.function(pip=["fastapi", "uvicorn"])
def api(port):
    from fastapi import FastAPI
    import uvicorn

    app = FastAPI()

    @app.get("/")
    def root():
        return {"status": "ok"}

    uvicorn.run(app, host="0.0.0.0", port=port)

api.run(port=8000)  # Accessible at localhost:8000
```

The container's port is automatically mapped to your host.

---

## Comparison with `@cycls.agent`

| Feature | `@cycls.function` | `@cycls.agent` |
|---------|-------------------|----------------|
| Use case | General Python functions | Chat/streaming agents |
| Input | Any arguments | `context.messages` |
| Output | Return value or generator | Yield streaming responses |
| API | `.run()`, `.stream()`, `.watch()`, `.build()`, `.deploy()` | `.local()`, `.deploy()` |
| Web UI | No | Yes |
| Streaming | Yes (via `.stream()` + gRPC) | Yes (SSE) |

Use `@cycls.function` for batch processing, data pipelines, or any non-interactive workload. Use `@cycls.agent` for conversational AI with streaming responses.

---

## Summary

| Step | What Happens |
|------|--------------|
| **Decorate** | `@cycls.function(pip=[...])` wraps your function in a Runtime |
| **Serialize** | cloudpickle captures the function and all references |
| **Hash** | Dependencies are hashed into a deterministic image tag |
| **Build** | Docker image is built (or loaded from cache) |
| **Run** | Container executes, result is deserialized and returned |
