# Volumes

Named, persistent storage — created once, attached to any deployment at any
mount path, alive for as long as you want regardless of what gets deployed
or deleted around it.

```python
import cycls

data = cycls.Volume("training-data")

@cycls.function(volumes={"/data": data})
def crunch(day):
    import pandas as pd
    return pd.read_parquet(f"/data/events-{day}.parquet").sum()
```

Inside the container, `/data` is the volume. Files written there persist
across calls, instances, and redeploys — and any *other* deployment that
mounts `training-data` sees the same files.

## The mental model

A volume is **shared files, not a database**. Reads and writes are plain
filesystem operations. Two things follow:

- Concurrent writers to the *same file* are last-write-wins. There is no
  locking. Give concurrent writers distinct files (per-user paths, per-run
  outputs) and you'll never notice.
- A file written by one deployment becomes visible to others within
  seconds, not instantly.

## Creating volumes

Referencing a volume creates it: the first deploy that mentions
`training-data` brings it into existence, and the deploy output says so —
`Created new volume 'training-data'` — so a typo'd name is a visible oops,
not a silent empty volume. If you prefer explicit-first:

```bash
cycls volume create training-data
```

Uploads never create volumes; `cycls volume put` to an unknown name is an
error pointing at `create`.

## Attaching

`volumes=` maps mount paths to `Volume` objects on any decorator —
`@cycls.function`, `@cycls.app`, `@cycls.agent`:

```python
state = cycls.Volume("staging-state")
prod_data = cycls.Volume("app-data")

@cycls.app(name="staging", volumes={
    "/workspace": state,
    "/prod": prod_data.read_only(),               # can't write prod from staging
    "/users": prod_data.sub_path("users/123"),    # mount one subtree only
})
def staging(port): ...
```

- `.read_only()` — mount without write access. The canonical use: prod data
  visible inside a dev deployment that can't corrupt it.
- `.sub_path("a/b")` — mount only a subdirectory of the volume.

**The workspace.** `/workspace` is the well-known path where apps and agents
keep their state — chats, `workspace`/`db` files. The path is convention;
the volume backing it is always yours, declared explicitly like any other.
Agents require one (the decorator errors without a `/workspace` entry);
apps only need one if they use `workspace`/`db` — the error arrives on
first use otherwise. Nothing is ever named or created implicitly: your
storage is exactly what your source declares. Renaming a deployment
changes nothing about its data — the volume reference is the identity.

Mounting one workspace volume into two *live* apps or agents means
concurrent writers on state — last-write-wins applies to your sessions.
Legal (blue/green cutovers), sharp if done casually.

Local `cycls run` ignores volumes — they exist in the cloud; locally your
code just sees the local filesystem.

## Lifecycle

Volumes outlive deployments — that's the point:

- `cycls rm <deployment>` **detaches** its volumes; the data is untouched.
  Redeploying the same name re-attaches them, files intact.
- Deleting data is always explicit: `cycls volume delete <name>`. It refuses
  while any deployment has the volume attached (the error names them), and
  deleted volumes remain recoverable for 7 days — if you deleted the wrong
  thing, contact support before the week is out.

## Moving data in and out

The CLI talks directly to storage — uploads and downloads don't proxy
through the API, so file size is effectively unlimited:

```bash
cycls volume put training-data ./model.bin models/model.bin
cycls volume get training-data outputs/result.parquet .
cycls volume ls training-data            # contents
cycls volume ls training-data models/    # contents under a prefix
cycls volume rm training-data models/old.bin
cycls volume ls                          # all volumes, with attachments
```

`put`/`get` are how you seed a model or dataset before anything is
deployed, and how you pull results out without writing an endpoint.

## Sharing across deployments

Because attachment is by name, a family of deployments can work one dataset:

```python
shared = cycls.Volume("pipeline")

@cycls.function(volumes={"/pipe": shared})
def extract(day): ...      # writes /pipe/raw/<day>.json

@cycls.function(volumes={"/pipe": shared})
def transform(day): ...    # reads raw/, writes clean/

@cycls.app(name="dashboard", volumes={"/pipe": shared.read_only()})
def dashboard(port): ...   # serves clean/, can't corrupt it
```

One volume, three deployments, no copying — and deleting any of the three
never touches the data.
