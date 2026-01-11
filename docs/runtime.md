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

The decorated function becomes a `Runtime` object with three methods:

### `.run(*args, **kwargs)`

Execute the function in a container and return the result.

```python
@cycls.function(pip=["numpy"])
def add(a, b):
    import numpy as np
    return np.add(a, b).tolist()

result = add.run([1, 2], [3, 4])  # [4, 6]
```

- Builds the container image if needed (cached for subsequent runs)
- Serializes the function and arguments
- Runs the container
- Streams logs to stdout
- Returns the deserialized result

### `.build(*args, **kwargs)`

Build a self-contained Docker image without running it.

```python
@cycls.function(pip=["fastapi", "uvicorn"])
def api(port):
    ...

image_tag = api.build(port=8000)
# Returns: "cycls/api:deploy-abc123"
```

The resulting image can be run anywhere:

```bash
docker run -p 8000:8000 cycls/api:deploy-abc123
```

### `.deploy(*args, **kwargs)`

Deploy the function to the Cycls cloud.

```python
@cycls.function(pip=["numpy"], key="YOUR_API_KEY")
def compute(data):
    ...

url = compute.deploy(data=[1, 2, 3])
# Returns: "https://compute.cycls.ai"
```

---

## How It Works

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

### 3. Multi-Stage Docker Build

Cycls generates a Dockerfile with two stages:

**Stage 1: Base** - All dependencies installed
```dockerfile
FROM python:3.11-slim as base
RUN apt-get install -y ffmpeg
RUN pip install numpy pandas
COPY utils.py /app/
```

**Stage 2: Final** - Function payload baked in
```dockerfile
FROM base
COPY payload.pkl /app/io/
```

### 4. Execution Flow

```
┌─────────────────┐
│  Your Function  │
└────────┬────────┘
         │ cloudpickle.dumps()
         ▼
┌─────────────────┐
│   payload.pkl   │
└────────┬────────┘
         │ mounted into container
         ▼
┌─────────────────┐
│    Container    │
│  ┌───────────┐  │
│  │ runner.py │  │──▶ cloudpickle.loads(payload)
│  └───────────┘  │──▶ result = func(*args, **kwargs)
│                 │──▶ cloudpickle.dumps(result)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   result.pkl    │
└────────┬────────┘
         │ cloudpickle.loads()
         ▼
┌─────────────────┐
│  Python Result  │
└─────────────────┘
```

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

## Comparison with `cycls.Agent`

| Feature | `@cycls.function` | `@agent()` |
|---------|-------------------|------------|
| Use case | General Python functions | Chat/streaming agents |
| Input | Any arguments | `context.messages` |
| Output | Return value | Yield streaming responses |
| API | `.run()`, `.build()`, `.deploy()` | `.local()`, `.deploy()` |
| Web UI | No | Yes |
| Streaming | No | Yes (SSE) |
| Hot-reload | No | Yes (`.local(watch=True)`) |

Use `@cycls.function` for batch processing, data pipelines, or any non-interactive workload. Use `@agent()` for conversational AI with streaming responses.

---

## Summary

| Step | What Happens |
|------|--------------|
| **Decorate** | `@cycls.function(pip=[...])` wraps your function in a Runtime |
| **Serialize** | cloudpickle captures the function and all references |
| **Hash** | Dependencies are hashed into a deterministic image tag |
| **Build** | Docker image is built (or loaded from cache) |
| **Run** | Container executes, result is deserialized and returned |
