# Examples

Every example runs with the CLI. `run` is local Docker, `--remote` is the cloud,
`deploy` freezes and publishes.

```bash
pip install cycls               # or, in this repo: uv sync --group test
export CYCLS_API_KEY=...        # from https://cloud.cycls.com
uv run cycls run examples/functions/hello.py --n 8
```

Agent examples read provider keys from `.env` inside the container. Keep two
files: `.env` on your machine for `CYCLS_API_KEY`, and `.providers.env` for
`ANTHROPIC_API_KEY` and friends, copied in as `.env` by the image.

## Functions

Containerized Python. Run it locally, run it in the cloud, or freeze it as a
named endpoint.

| File | Shows |
| --- | --- |
| [functions/hello.py](functions/hello.py) | the smallest function, and argument binding from the CLI |
| [functions/dev_loop.py](functions/dev_loop.py) | `--remote`, `local_entrypoint`, and `.map()` |
| [functions/fanout.py](functions/fanout.py) | one call per item across instances, errors returned as data |
| [functions/warm_model.py](functions/warm_model.py) | an embedding model loaded once per instance |
| [functions/toolchain.py](functions/toolchain.py) | apt packages and an arbitrary toolchain in the image |
| [functions/nightly.py](functions/nightly.py) | a scheduled function writing to a volume |

## Warehouse

Parquet on a volume, DuckDB in a function, an agent on top.

| File | Shows |
| --- | --- |
| [warehouse/ingest.py](warehouse/ingest.py) | CSV to partitioned Parquet, a nightly schedule, a backfill |
| [warehouse/query.py](warehouse/query.py) | DuckDB over the partitions on a read-only mount |
| [warehouse/analyst.py](warehouse/analyst.py) | an agent that calls the deployed query endpoint as a tool |

## Apps

A blocking ASGI service with sign-in and per-user storage.

| File | Shows |
| --- | --- |
| [apps/api.py](apps/api.py) | the smallest app, and the `--remote` dev URL |
| [apps/notes/](apps/notes/) | an inverted index over `cycls.DB`, with a bundled front end |
| [apps/terminal/](apps/terminal/) | a per-user sandboxed shell using `cycls.Sandbox` |

## Agents

A chat product with a managed model loop, tools, files and a web interface.

| File | Shows |
| --- | --- |
| [agents/minimal.py](agents/minimal.py) | the smallest agent, with built-in tools and cost tracking |
| [agents/tools.py](agents/tools.py) | custom tool schemas, handlers, labels and a component return |
| [agents/open_model.py](agents/open_model.py) | DeepSeek, Kimi, GLM and your own vLLM or SGLang server |
| [agents/super.py](agents/super.py) | production shape: branding, CMS, workspaces, analytics, quotas |
| [agents/catalog.py](agents/catalog.py) | a connector catalog declared once and shared |

## Services

| Path | Shows |
| --- | --- |
| [browser_service/](browser_service/) | deploying the shared browser service the `Browser` tool calls |

## Documentation

Full guides and reference: [docs.cycls.com](https://docs.cycls.com).

| Topic | Page |
| --- | --- |
| Functions, remote execution | [docs/function.md](../docs/function.md) |
| Volumes | [docs/volume.md](../docs/volume.md) |
| Cron | [docs/cron.md](../docs/cron.md) |
| Workspaces | [docs/workspaces.md](../docs/workspaces.md) |
| CLI | [docs/cli.md](../docs/cli.md) |
| Everything, end to end | [docs/tutorial.md](../docs/tutorial.md) |
