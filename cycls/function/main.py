import contextlib
import cloudpickle
import tempfile
import hashlib
import json
import os
import sys
import shutil
import traceback
from pathlib import Path
import tarfile

os.environ["DOCKER_BUILDKIT"] = "1"

ENTRYPOINT_PY = '''import sys
sys.path.insert(0, '/app')
import cloudpickle
with open("/app/function.pkl", "rb") as f:
    func, args, kwargs = cloudpickle.load(f)
func(*args, **kwargs)
'''

RUNNER_PY = '''import sys
sys.path.insert(0, '/app')
import cloudpickle
import traceback
from pathlib import Path

io_dir = Path(sys.argv[1])
payload_path = io_dir / "payload.pkl"
result_path = io_dir / "result.pkl"

try:
    with open(payload_path, "rb") as f:
        func, args, kwargs = cloudpickle.load(f)
    result = func(*args, **kwargs)
    with open(result_path, "wb") as f:
        cloudpickle.dump(result, f)
except Exception:
    traceback.print_exc()
    sys.exit(1)
'''

# Module-level configuration
api_key = None
base_url = None

def _get_api_key():
    import sys
    cycls_pkg = sys.modules.get('cycls')
    return api_key or (cycls_pkg and cycls_pkg.__dict__.get('api_key')) or os.getenv("CYCLS_API_KEY")

def _get_base_url():
    import sys
    cycls_pkg = sys.modules.get('cycls')
    return base_url or (cycls_pkg and cycls_pkg.__dict__.get('base_url')) or os.getenv("CYCLS_BASE_URL")

def _hash_path(path_str: str) -> str:
    h = hashlib.sha256()
    p = Path(path_str)
    if p.is_file():
        with p.open('rb') as f:
            while chunk := f.read(65536):
                h.update(chunk)
    elif p.is_dir():
        for root, dirs, files in os.walk(p, topdown=True):
            dirs.sort()
            files.sort()
            for name in files:
                filepath = Path(root) / name
                h.update(str(filepath.relative_to(p)).encode())
                with filepath.open('rb') as f:
                    while chunk := f.read(65536):
                        h.update(chunk)
    return h.hexdigest()


def _copy_path(src_path: Path, dest_path: Path):
    if src_path.is_dir():
        shutil.copytree(src_path, dest_path, dirs_exist_ok=True)
    else:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src_path, dest_path)


class Function:
    """Executes functions in Docker containers."""

    _base_pip = []
    _base_apt = []

    def __init__(self, func, name, python_version=None, image=None,
                 base_url=None, api_key=None):
        image = image or {}
        self.func = func
        self.name = name.replace('_', '-')
        host_py = f"{sys.version_info.major}.{sys.version_info.minor}"
        if python_version and ".".join(str(python_version).split(".")[:2]) != host_py:
            raise ValueError(
                f"python_version={python_version!r} doesn't match the host's {host_py}: "
                "functions ship as cloudpickle bytecode, which only loads on the same "
                "major.minor Python.")
        self.python_version = python_version or host_py
        self.base_image = f"python:{self.python_version}-slim"
        self.apt = sorted([*self._base_apt, *image.get("apt", [])])
        self.run_commands = list(image.get("run_commands", []))
        self.copy = image.get("copy", {})
        self._base_url = base_url
        self._api_key = api_key
        self.pip = sorted(set([*self._base_pip, *image.get("pip", [])])
                          | {f"cloudpickle=={cloudpickle.__version__}"})
        self.force_rebuild = image.get("force_rebuild", False)

        self.image_prefix = f"cycls/{self.name}"
        self.managed_label = "cycls.function"
        self._docker_client = None
        self._container = None

    def __getstate__(self):
        state = self.__dict__.copy()
        state["_docker_client"] = None
        state["_container"] = None
        return state

    @property
    def api_key(self):
        return self._api_key or _get_api_key()

    @property
    def base_url(self):
        return self._base_url or _get_base_url() or "https://api.cycls.ai"

    @property
    def docker_client(self):
        if self._docker_client is None:
            import docker
            try:
                print("Initializing Docker client...")
                client = docker.from_env()
                client.ping()
                self._docker_client = client
            except docker.errors.DockerException:
                print("\nError: Docker is not running or is not installed.")
                print("Please start the Docker daemon and try again.")
                sys.exit(1)
        return self._docker_client

    def _perform_auto_cleanup(self, keep_tag=None):
        try:
            current_id = self._container.id if self._container else None
            for container in self.docker_client.containers.list(all=True, filters={"label": self.managed_label}):
                if container.id != current_id:
                    container.remove(force=True)

            cleaned = 0
            for image in self.docker_client.images.list(filters={"label": self.managed_label}):
                is_deploy = any(":deploy-" in t for t in image.tags)
                is_current = keep_tag and keep_tag in image.tags
                if not is_deploy and not is_current:
                    self.docker_client.images.remove(image.id, force=True)
                    cleaned += 1
            if cleaned:
                print(f"Cleaned up {cleaned} old dev image(s).")
        except Exception as e:
            print(f"Warning: cleanup error: {e}")

    def _image_tag(self, extra_parts=None) -> str:
        parts = [self.base_image, self.python_version, self.pip,
                 self.apt, self.run_commands]
        for src, dst in sorted(self.copy.items()):
            if not Path(src).exists():
                raise FileNotFoundError(f"Path in 'copy' not found: {src}")
            parts.append(f"{src}>{dst}:{_hash_path(src)}")
        if extra_parts:
            parts.extend(extra_parts)
        return f"{self.image_prefix}:{hashlib.sha256(json.dumps(parts).encode()).hexdigest()[:16]}"

    def _dockerfile_preamble(self) -> str:
        lines = [
            f"FROM {self.base_image}",
            "ENV PIP_ROOT_USER_ACTION=ignore PYTHONUNBUFFERED=1",
            "WORKDIR /app",
            "RUN pip install uv",
        ]

        if self.apt:
            lines.append(f"RUN apt-get update && apt-get install -y --no-install-recommends {' '.join(self.apt)}")

        if self.pip:
            lines.append(f"RUN uv pip install --system --no-cache {' '.join(self.pip)}")

        for cmd in self.run_commands:
            lines.append(f"RUN {cmd}")

        for dst in self.copy.values():
            lines.append(f"COPY context_files/{dst} /app/{dst}")

        return "\n".join(lines)

    def _dockerfile_local(self) -> str:
        return f"""{self._dockerfile_preamble()}
COPY runner.py /runner.py
ENTRYPOINT ["python", "/runner.py", "/io"]
"""

    def _dockerfile_deploy(self, port: int) -> str:
        return f"""{self._dockerfile_preamble()}
COPY function.pkl /app/function.pkl
COPY entrypoint.py /app/entrypoint.py
EXPOSE {port}
CMD ["python", "entrypoint.py"]
"""

    def _copy_user_files(self, workdir: Path):
        context_files_dir = workdir / "context_files"
        context_files_dir.mkdir()
        for src, dst in self.copy.items():
            _copy_path(Path(src).resolve(), context_files_dir / dst)

    def _build_image(self, tag: str, workdir: Path) -> str:
        import docker
        print("--- Docker Build Logs ---")
        force = os.environ.get('_CYCLS_FORCE_REBUILD') == '1' if os.environ.get('_CYCLS_WATCH') else self.force_rebuild
        try:
            for chunk in self.docker_client.api.build(
                path=str(workdir), tag=tag, forcerm=True, decode=True,
                nocache=force, labels={self.managed_label: "true"}
            ):
                if 'stream' in chunk:
                    print(chunk['stream'].strip())
            print("-------------------------")
            print(f"Image built: {tag}")
            return tag
        except docker.errors.BuildError as e:
            print(f"\nDocker build failed: {e}")
            raise

    def _ensure_local_image(self) -> str:
        import docker
        tag = self._image_tag(extra_parts=["local-v1"])
        force = os.environ.get('_CYCLS_FORCE_REBUILD') == '1' if os.environ.get('_CYCLS_WATCH') else self.force_rebuild
        if not force:
            try:
                self.docker_client.images.get(tag)
                print(f"Found cached image: {tag}")
                return tag
            except docker.errors.ImageNotFound:
                pass
        print(f"Building new image: {tag}")

        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            self._copy_user_files(workdir)
            (workdir / "Dockerfile").write_text(self._dockerfile_local())
            (workdir / "runner.py").write_text(RUNNER_PY)
            return self._build_image(tag, workdir)

    def _cleanup_container(self):
        if getattr(self, '_container', None):
            import docker
            try:
                self._container.stop(timeout=3)
                self._container.remove()
            except docker.errors.NotFound:
                pass
            except docker.errors.APIError:
                pass
            self._container = None

    @contextlib.contextmanager
    def runner(self, *args, **kwargs):
        service_port = kwargs.get('port')
        tag = self._ensure_local_image()
        self._perform_auto_cleanup(keep_tag=tag)

        ports = {f'{service_port}/tcp': service_port} if service_port else None

        with tempfile.TemporaryDirectory() as io_dir:
            io_path = Path(io_dir)
            payload_path = io_path / "payload.pkl"
            result_path = io_path / "result.pkl"

            with open(payload_path, 'wb') as f:
                cloudpickle.dump((self.func, args, kwargs), f)

            try:
                self._container = self.docker_client.containers.create(
                    image=tag,
                    volumes={str(io_path): {'bind': '/io', 'mode': 'rw'}},
                    ports=ports,
                    labels={self.managed_label: "true"}, 
                    cap_add=["SYS_ADMIN"], security_opt=["apparmor=unconfined", "seccomp=unconfined"]  # local bubblewrap
                )
                self._container.start()
                yield self._container, result_path
            finally:
                self._cleanup_container()

    def run(self, *args, **kwargs):
        service_port = kwargs.get('port')
        print(f"Running '{self.name}'...")

        try:
            with self.runner(*args, **kwargs) as (container, result_path):
                print("--- Container Logs ---")
                for chunk in container.logs(stream=True, follow=True):
                    print(chunk.decode(), end='')
                print("----------------------")

                status = container.wait()
                if status['StatusCode'] != 0:
                    print(f"Error: Container exited with code {status['StatusCode']}")
                    return None

                if service_port:
                    return None

                if result_path.exists():
                    with open(result_path, 'rb') as f:
                        return cloudpickle.load(f)
                else:
                    print("Error: Result file not found")
                    return None

        except KeyboardInterrupt:
            print("\n----------------------")
            print("Stopping...")
            return None
        except Exception:
            traceback.print_exc()
            return None

    def watch(self, *args, **kwargs):
        if os.environ.get('_CYCLS_WATCH'):
            return self.run(*args, **kwargs)

        try:
            from watchfiles import watch as watchfiles_watch
        except ImportError:
            print("watchfiles not installed. pip install watchfiles")
            return self.run(*args, **kwargs)

        import subprocess

        # CLI sets _source_file to the user's .py path; script mode falls back to argv[0].
        script = Path(getattr(self, '_source_file', None) or sys.argv[0]).resolve()
        watch_paths = [script] + [Path(p).resolve() for p in self.copy if Path(p).exists()]

        print(f"Watching: {[p.name for p in watch_paths]}\n")

        first_run = True
        while True:
            env = {**os.environ, '_CYCLS_WATCH': '1'}
            # Force rebuild only on first run, then use cache for subsequent reloads
            env['_CYCLS_FORCE_REBUILD'] = '1' if (self.force_rebuild and first_run) else '0'

            # Respawn with the exact argv that launched us — works for both
            # `python super.py` (argv=['super.py']) and
            # `cycls run super.py` (argv=['/.../cycls', 'run', 'super.py']).
            proc = subprocess.Popen([sys.executable, *sys.argv], env=env)
            first_run = False
            try:
                for changes in watchfiles_watch(*watch_paths):
                    print(f"\nChanged: {[Path(c[1]).name for c in changes]}")
                    break
                proc.terminate()
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
            except KeyboardInterrupt:
                proc.terminate()
                proc.wait(timeout=3)
                return

    def _prepare_deploy_context(self, workdir: Path, port: int, args=(), kwargs=None, remote=False):
        kwargs = kwargs or {}
        kwargs['port'] = port
        self._copy_user_files(workdir)
        (workdir / "Dockerfile").write_text(self._dockerfile_deploy(port))
        if remote:
            from .remote import REMOTE_PY, token_for
            (workdir / "entrypoint.py").write_text(REMOTE_PY)
            payload = (self.func, token_for(self.api_key or "dev", self.name))
        else:
            (workdir / "entrypoint.py").write_text(ENTRYPOINT_PY)
            payload = (self.func, args, kwargs)
        with open(workdir / "function.pkl", "wb") as f:
            cloudpickle.dump(payload, f)

    def build(self, *args, **kwargs):
        import docker
        port = kwargs.pop('port', 8080)
        payload = cloudpickle.dumps((self.func, args, {**kwargs, 'port': port}))
        tag = f"{self.image_prefix}:deploy-{hashlib.sha256(payload).hexdigest()[:16]}"

        try:
            self.docker_client.images.get(tag)
            print(f"Found cached image: {tag}")
            return tag
        except docker.errors.ImageNotFound:
            print(f"Building: {tag}")

        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            self._prepare_deploy_context(workdir, port, args, kwargs)
            self._build_image(tag, workdir)
            print(f"Run: docker run --rm -p {port}:{port} {tag}")
            return tag

    def _is_remote(self):
        """A function that can't accept the injected `port` (no `port` param,
        no **kwargs) isn't a server — deploy it as a callable endpoint."""
        import inspect
        try:
            params = inspect.signature(self.func).parameters.values()
        except (ValueError, TypeError):
            return False
        return not any(p.name == "port" or p.kind == p.VAR_KEYWORD for p in params)

    def deploy(self, *args, **kwargs):
        import requests

        base_url = self.base_url
        port = kwargs.pop('port', 8080)
        memory = kwargs.pop('memory', '1Gi')
        remote = kwargs.pop('remote', None)
        if remote is None:
            remote = self._is_remote()

        # Check name availability before uploading
        print(f"Checking '{self.name}'...")
        try:
            check_resp = requests.get(
                f"{base_url}/v1/deployment/check-name",
                params={"name": self.name},
                headers={"X-API-Key": self.api_key},
                timeout=30,
            )
            if check_resp.status_code == 401:
                print("Error: Invalid API key")
                return None
            check_resp.raise_for_status()
            check_data = check_resp.json()
            if not check_data.get("available"):
                print(f"Error: {check_data.get('reason', 'Name unavailable')}")
                return None
        except requests.exceptions.RequestException as e:
            print(f"Error checking name: {e}")
            return None

        print(f"Deploying '{self.name}'...")

        payload = cloudpickle.dumps((self.func, args, {**kwargs, 'port': port}))
        archive_name = f"{self.name}-{hashlib.sha256(payload).hexdigest()[:16]}.tar.gz"

        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            self._prepare_deploy_context(workdir, port, args, kwargs, remote=remote)

            archive_path = workdir / archive_name
            with tarfile.open(archive_path, "w:gz") as tar:
                for f in workdir.glob("**/*"):
                    if f.is_file() and f != archive_path:
                        tar.add(f, arcname=f.relative_to(workdir))

            print("Uploading...")
            upload_resp = requests.post(
                f"{base_url}/v1/deploy/upload",
                data={"function_name": self.name},
                headers={"X-API-Key": self.api_key},
                timeout=30,
            )
            if not upload_resp.ok:
                print(f"Upload request failed: {upload_resp.status_code}")
                try:
                    print(f"  {upload_resp.json()['detail']}")
                except (json.JSONDecodeError, KeyError):
                    print(f"  {upload_resp.text}")
                return None
            upload_data = upload_resp.json()

            with open(archive_path, 'rb') as f:
                gcs_resp = requests.put(
                    upload_data["upload_url"],
                    data=f,
                    headers={"Content-Type": "application/gzip"},
                    timeout=9000,
                )
            if not gcs_resp.ok:
                print(f"Archive upload failed: {gcs_resp.status_code}")
                return None

            response = requests.post(
                f"{base_url}/v1/deploy",
                data={
                    "function_name": self.name,
                    "source_object": upload_data["object_name"],
                    "port": port,
                    "memory": memory,
                    "timeout": 1200,
                    # The remote shim is stdlib http.server — HTTP/1.1 only;
                    # h2c end-to-end would 502 it.
                    "use_http2": "false" if remote else "true",
                    "session_affinity": "true",
                },
                headers={"X-API-Key": self.api_key},
                timeout=9000,
                stream=True,
            )

            if not response.ok:
                print(f"Deploy failed: {response.status_code}")
                try:
                    print(f"  {response.json()['detail']}")
                except (json.JSONDecodeError, KeyError):
                    print(f"  {response.text}")
                return None

            # Parse NDJSON stream
            url = None
            for line in response.iter_lines(decode_unicode=True):
                if line:
                    event = json.loads(line)
                    status = event.get("status", "")
                    msg = event.get("message", "")
                    print(f"  [{status}] {msg}")
                    if status == "DONE":
                        url = event.get("url")
                        print(f"Deployed: {url}")
                        if remote and not self.name.startswith("exec-"):
                            print(f'Call it: cycls.remote("{self.name}")(...)')
                    elif status == "ERROR":
                        return None
            return url

    def _executor_name(self):
        # Per-image, name-independent: functions sharing an image share one
        # executor; different deps (or python) → a different one.
        return f"exec-{self._image_tag().rsplit(':', 1)[1]}"

    def remote(self, *args, **kwargs):
        """Run this function's CURRENT code in the cloud — ships the live
        bytecode to a per-image executor, provisioned once on first call.
        (cycls.remote(name) calls a frozen deployment by name instead.)"""
        return self._on_executor(lambda call: call(self.func, *args, **kwargs))

    def map(self, items, *, workers=16):
        """Fan this function's CURRENT code out across autoscaled instances —
        one cloud call per item, results in input order."""
        from concurrent.futures import ThreadPoolExecutor
        items = list(items)   # retry after provisioning must re-iterate
        def fan(call):
            with ThreadPoolExecutor(workers) as pool:
                return list(pool.map(lambda item: call(self.func, item), items))
        return self._on_executor(fan)

    def _on_executor(self, op):
        """Run `op(call)` against this image's executor, provisioning it on
        the first 404 (missing service — user errors keep their own status)."""
        import time
        from .remote import remote as _remote, RemoteError
        call = _remote(self._executor_name(), api_key=self._api_key)
        try:
            return op(call)
        except RemoteError as e:
            if e.status != 404: raise
        print(f"Provisioning executor '{self._executor_name()}' (one-time for this image)...")
        self._deploy_executor(self._executor_name())
        for _ in range(15):
            try:
                return op(call)
            except RemoteError as e:
                if e.status != 404: raise
                time.sleep(2)
        raise RemoteError(f"executor {self._executor_name()!r} deployed but never became reachable")

    def _deploy_executor(self, name):
        from .remote import RemoteError
        def execute(fn, *args, **kwargs):   # local → pickles by value (image has no cycls)
            return fn(*args, **kwargs)
        image = {"pip": self.pip, "apt": self.apt,
                 "run_commands": self.run_commands, "copy": self.copy}
        # remote=True is required: execute's **kwargs reads as a server signature.
        if not Function(execute, name, image=image, api_key=self._api_key).deploy(remote=True):
            raise RemoteError(f"provisioning {name!r} failed")

    def __del__(self):
        self._cleanup_container()


def function(name=None, image=None, **kwargs):
    """Decorator that transforms a Python function into a containerized Function.
    Build config (pip, apt, run_commands, copy, force_rebuild) must be passed
    via `image=cycls.Image()...` — flat kwargs are not accepted."""
    def decorator(func):
        return Function(func, name or func.__name__, image=image, **kwargs,
                        base_url=_get_base_url(), api_key=_get_api_key())
    return decorator
