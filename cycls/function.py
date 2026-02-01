import contextlib
import docker
import cloudpickle
import tempfile
import hashlib
import json
import os
import sys
import shutil
from pathlib import Path
import tarfile
from dotenv import load_dotenv

load_dotenv()

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

    def __init__(self, func, name, python_version=None, pip=None, apt=None,
                 run_commands=None, copy=None, base_url=None, api_key=None):
        self.func = func
        self.name = name.replace('_', '-')
        self.python_version = python_version or f"{sys.version_info.major}.{sys.version_info.minor}"
        self.base_image = f"python:{self.python_version}-slim"
        self.apt = sorted(apt or [])
        self.run_commands = sorted(run_commands or [])
        self.copy = {f: f for f in copy} if isinstance(copy, list) else (copy or {})
        self._base_url = base_url
        self._api_key = api_key
        self.pip = sorted(set(pip or []) | {"cloudpickle"})

        self.image_prefix = f"cycls/{self.name}"
        self.managed_label = "cycls.function"
        self._docker_client = None
        self._container = None

    @property
    def api_key(self):
        return self._api_key or _get_api_key()

    @property
    def base_url(self):
        return self._base_url or _get_base_url() or "https://api.cycls.ai"

    @property
    def docker_client(self):
        if self._docker_client is None:
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
        parts = [self.base_image, self.python_version, "".join(self.pip),
                 "".join(self.apt), "".join(self.run_commands)]
        for src, dst in sorted(self.copy.items()):
            if not Path(src).exists():
                raise FileNotFoundError(f"Path in 'copy' not found: {src}")
            parts.append(f"{src}>{dst}:{_hash_path(src)}")
        if extra_parts:
            parts.extend(extra_parts)
        return f"{self.image_prefix}:{hashlib.sha256(''.join(parts).encode()).hexdigest()[:16]}"

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
        print("--- Docker Build Logs ---")
        try:
            for chunk in self.docker_client.api.build(
                path=str(workdir), tag=tag, forcerm=True, decode=True,
                labels={self.managed_label: "true"}
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
        tag = self._image_tag(extra_parts=["local-v1"])
        try:
            self.docker_client.images.get(tag)
            print(f"Found cached image: {tag}")
            return tag
        except docker.errors.ImageNotFound:
            print(f"Building new image: {tag}")

        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            self._copy_user_files(workdir)
            (workdir / "Dockerfile").write_text(self._dockerfile_local())
            (workdir / "runner.py").write_text(RUNNER_PY)
            return self._build_image(tag, workdir)

    def _cleanup_container(self):
        if getattr(self, '_container', None):
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
                    labels={self.managed_label: "true"}
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
        except Exception as e:
            print(f"Error: {e}")
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

        script = Path(sys.argv[0]).resolve()
        watch_paths = [script] + [Path(p).resolve() for p in self.copy if Path(p).exists()]

        print(f"Watching: {[p.name for p in watch_paths]}\n")

        while True:
            proc = subprocess.Popen([sys.executable, str(script)], env={**os.environ, '_CYCLS_WATCH': '1'})
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

    def _prepare_deploy_context(self, workdir: Path, port: int, args=(), kwargs=None):
        kwargs = kwargs or {}
        kwargs['port'] = port
        self._copy_user_files(workdir)
        (workdir / "Dockerfile").write_text(self._dockerfile_deploy(port))
        (workdir / "entrypoint.py").write_text(ENTRYPOINT_PY)
        with open(workdir / "function.pkl", "wb") as f:
            cloudpickle.dump((self.func, args, kwargs), f)

    def build(self, *args, **kwargs):
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

    def deploy(self, *args, **kwargs):
        import requests

        base_url = self.base_url
        port = kwargs.pop('port', 8080)
        memory = kwargs.pop('memory', '1Gi')

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
            self._prepare_deploy_context(workdir, port, args, kwargs)

            archive_path = workdir / archive_name
            with tarfile.open(archive_path, "w:gz") as tar:
                for f in workdir.glob("**/*"):
                    if f.is_file() and f != archive_path:
                        tar.add(f, arcname=f.relative_to(workdir))

            print("Uploading...")
            with open(archive_path, 'rb') as f:
                response = requests.post(
                    f"{base_url}/v1/deploy",
                    data={"function_name": self.name, "port": port, "memory": memory},
                    files={'source_archive': (archive_name, f, 'application/gzip')},
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
                    elif status == "ERROR":
                        return None
            return url

    def __del__(self):
        self._cleanup_container()


def function(name=None, **kwargs):
    """Decorator that transforms a Python function into a containerized Function."""
    def decorator(func):
        return Function(func, name or func.__name__, **kwargs, base_url=_get_base_url(), api_key=_get_api_key())
    return decorator
