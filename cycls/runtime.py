import contextlib
import docker
import cloudpickle
import tempfile
import hashlib
import os
import sys
import shutil
from pathlib import Path
import tarfile

from .grpc import RuntimeClient

os.environ["DOCKER_BUILDKIT"] = "1"

GRPC_PORT = 50051
BASE_IMAGE = "ghcr.io/cycls/base:python3.12"
BASE_PACKAGES = {"cloudpickle", "cryptography", "fastapi", "fastapi[standard]",
                 "pydantic", "pyjwt", "uvicorn", "uvicorn[standard]", "httpx"}
GRPC_PACKAGES = {"grpcio", "protobuf"}

# Simple entrypoint for deployed services - loads pickled function+args and runs it
ENTRYPOINT_PY = '''import cloudpickle
with open("/app/function.pkl", "rb") as f:
    func, args, kwargs = cloudpickle.load(f)
func(*args, **kwargs)
'''


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


class Runtime:
    """Executes functions in Docker containers. Uses gRPC for local dev, pickle for deploy."""

    def __init__(self, func, name, python_version=None, pip_packages=None, apt_packages=None,
                 run_commands=None, copy=None, base_url=None, api_key=None, base_image=None):
        self.func = func
        self.name = name
        self.python_version = python_version or f"{sys.version_info.major}.{sys.version_info.minor}"
        self.apt_packages = sorted(apt_packages or [])
        self.run_commands = sorted(run_commands or [])
        self.copy = copy or {}
        self.base_image = base_image or BASE_IMAGE
        self.base_url = base_url or "https://service-core-280879789566.me-central1.run.app"
        self.api_key = api_key

        # Compute pip packages (gRPC only needed for local dev, added dynamically)
        user_packages = set(pip_packages or [])
        if self.base_image == BASE_IMAGE:
            self.pip_packages = sorted(user_packages - BASE_PACKAGES)
        else:
            self.pip_packages = sorted(user_packages | {"cloudpickle"})

        self.image_prefix = f"cycls/{name}"
        self.managed_label = "cycls.runtime"
        self._docker_client = None

        # Local dev state (gRPC container)
        self._container = None
        self._client = None
        self._host_port = None

    @property
    def docker_client(self):
        """Lazily initializes and returns a Docker client."""
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
        """Clean up old containers and dev images (preserve deploy-* images)."""
        try:
            # Remove old containers
            current_id = self._container.id if self._container else None
            for container in self.docker_client.containers.list(all=True, filters={"label": self.managed_label}):
                if container.id != current_id:
                    container.remove(force=True)

            # Remove old dev images globally (keep deploy-* and current)
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
        """Creates a unique tag based on image configuration."""
        parts = [self.base_image, self.python_version, "".join(self.pip_packages),
                 "".join(self.apt_packages), "".join(self.run_commands)]
        for src, dst in sorted(self.copy.items()):
            if not Path(src).exists():
                raise FileNotFoundError(f"Path in 'copy' not found: {src}")
            parts.append(f"{src}>{dst}:{_hash_path(src)}")
        if extra_parts:
            parts.extend(extra_parts)
        return f"{self.image_prefix}:{hashlib.sha256(''.join(parts).encode()).hexdigest()[:16]}"

    def _dockerfile_preamble(self, pip_extras=None) -> str:
        """Common Dockerfile setup: base image, apt, pip, run commands, copy."""
        lines = [f"FROM {self.base_image}"]

        if self.base_image != BASE_IMAGE:
            lines.append("ENV PIP_ROOT_USER_ACTION=ignore PYTHONUNBUFFERED=1")
            lines.append("WORKDIR /app")

        if self.apt_packages:
            lines.append(f"RUN apt-get update && apt-get install -y --no-install-recommends {' '.join(self.apt_packages)}")

        all_pip = list(self.pip_packages) + list(pip_extras or [])
        if all_pip:
            lines.append(f"RUN uv pip install --system --no-cache {' '.join(all_pip)}")

        for cmd in self.run_commands:
            lines.append(f"RUN {cmd}")

        for dst in self.copy.values():
            lines.append(f"COPY context_files/{dst} /app/{dst}")

        return "\n".join(lines)

    def _dockerfile_grpc(self) -> str:
        """Dockerfile for local dev: gRPC server."""
        return f"""{self._dockerfile_preamble(pip_extras=GRPC_PACKAGES)}
COPY grpc_runtime/ /app/grpc_runtime/
EXPOSE {GRPC_PORT}
CMD ["python", "-m", "grpc_runtime.server", "--port", "{GRPC_PORT}"]
"""

    def _dockerfile_deploy(self, port: int) -> str:
        """Dockerfile for deploy: baked-in function via pickle."""
        return f"""{self._dockerfile_preamble()}
COPY function.pkl /app/function.pkl
COPY entrypoint.py /app/entrypoint.py
EXPOSE {port}
CMD ["python", "entrypoint.py"]
"""

    def _copy_user_files(self, workdir: Path):
        """Copy user-specified files to build context."""
        context_files_dir = workdir / "context_files"
        context_files_dir.mkdir()
        for src, dst in self.copy.items():
            _copy_path(Path(src).resolve(), context_files_dir / dst)

    def _build_image(self, tag: str, workdir: Path) -> str:
        """Build a Docker image from a prepared context."""
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

    def _ensure_grpc_image(self) -> str:
        """Build local dev image with gRPC server if needed."""
        tag = self._image_tag(extra_parts=["grpc-v2"])
        try:
            self.docker_client.images.get(tag)
            print(f"Found cached image: {tag}")
            return tag
        except docker.errors.ImageNotFound:
            print(f"Building new image: {tag}")

        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            self._copy_user_files(workdir)
            (workdir / "Dockerfile").write_text(self._dockerfile_grpc())

            # Copy gRPC runtime
            grpc_src = Path(__file__).parent / "grpc"
            shutil.copytree(grpc_src, workdir / "grpc_runtime",
                          ignore=shutil.ignore_patterns('*.proto', '__pycache__'))

            return self._build_image(tag, workdir)

    def _ensure_container(self, service_port=None):
        """Start container if not running, return gRPC client."""
        if self._client and self._container:
            try:
                self._container.reload()
                if self._container.status == 'running':
                    return self._client
            except:
                pass
            self._cleanup_container()

        tag = self._ensure_grpc_image()
        self._perform_auto_cleanup(keep_tag=tag)

        # Port mappings (fixed ports avoid race conditions)
        ports = {f'{GRPC_PORT}/tcp': GRPC_PORT}
        if service_port:
            ports[f'{service_port}/tcp'] = service_port

        self._container = self.docker_client.containers.run(
            tag, detach=True, ports=ports, labels={self.managed_label: "true"}
        )
        self._host_port = GRPC_PORT
        self._client = RuntimeClient(port=self._host_port)
        if not self._client.wait_ready(timeout=10):
            raise RuntimeError("Container failed to start")
        print(f"Container ready on port {self._host_port}")
        return self._client

    def _cleanup_container(self):
        """Stop and remove the warm container."""
        if self._client:
            self._client.close()
            self._client = None
        if self._container:
            try:
                self._container.stop(timeout=3)
                self._container.remove()
            except:
                pass
            self._container = None
        self._host_port = None

    def run(self, *args, **kwargs):
        """Execute the function in a container and return the result."""
        service_port = kwargs.get('port')
        print(f"Running '{self.name}'...")
        try:
            client = self._ensure_container(service_port=service_port)

            # Blocking service: fire gRPC, stream Docker logs
            if service_port:
                client.fire(self.func, *args, **kwargs)
                print(f"Service running on port {service_port}")
                print("--- 🪵 Container Logs ---")
                for chunk in self._container.logs(stream=True, follow=True):
                    print(chunk.decode(), end='')
                return None

            # Regular function: execute, then print logs
            result = client.call(self.func, *args, **kwargs)
            logs = self._container.logs().decode()
            if logs.strip():
                print("--- 🪵 Container Logs ---")
                print(logs, end='')
                print("-------------------------")
            return result

        except KeyboardInterrupt:
            print("\n-------------------------")
            print("Stopping...")
            self._cleanup_container()
            return None
        except Exception as e:
            print(f"Error: {e}")
            return None

    def stream(self, *args, **kwargs):
        """Execute the function and yield streamed results."""
        service_port = kwargs.get('port')
        client = self._ensure_container(service_port=service_port)
        yield from client.execute(self.func, *args, **kwargs)

    @contextlib.contextmanager
    def runner(self, *args, **kwargs):
        """Context manager for running a service. Yields (container, client)."""
        service_port = kwargs.get('port')
        try:
            client = self._ensure_container(service_port=service_port)
            client.fire(self.func, *args, **kwargs)
            yield self._container, client
        finally:
            self._cleanup_container()

    def watch(self, *args, **kwargs):
        """Run with file watching - restarts script on changes."""
        try:
            from watchfiles import watch as watchfiles_watch
        except ImportError:
            print("watchfiles not installed. Run: pip install watchfiles")
            return

        import inspect
        import subprocess

        # Find the user's script (outside cycls package)
        cycls_pkg = Path(__file__).parent.resolve()
        main_script = None
        for frame_info in inspect.stack():
            filepath = Path(frame_info.filename).resolve()
            if filepath.suffix == '.py' and not str(filepath).startswith(str(cycls_pkg)):
                main_script = filepath
                break

        if not main_script:
            print("Could not find script to watch.")
            return self.run(*args, **kwargs)

        # Build watch paths
        watch_paths = [main_script]
        watch_paths.extend([Path(src).resolve() for src in self.copy.keys() if Path(src).exists()])

        print(f"👀 Watching:")
        for p in watch_paths:
            print(f"   {p}")
        print()

        while True:
            print(f"🚀 Starting {main_script.name}...")
            proc = subprocess.Popen(
                [sys.executable, str(main_script)],
                env={**os.environ, '_CYCLS_WATCH': '1'}
            )

            try:
                for changes in watchfiles_watch(*watch_paths):
                    print(f"\n🔄 Changed: {[Path(c[1]).name for c in changes]}")
                    break

                proc.terminate()
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
            except KeyboardInterrupt:
                print("\nStopping...")
                proc.terminate()
                proc.wait(timeout=3)
                return

            print()

    def _prepare_deploy_context(self, workdir: Path, port: int, args=(), kwargs=None):
        """Prepare build context for deploy: pickle function+args + entrypoint."""
        kwargs = kwargs or {}
        kwargs['port'] = port  # Ensure port is in kwargs
        self._copy_user_files(workdir)
        (workdir / "Dockerfile").write_text(self._dockerfile_deploy(port))
        (workdir / "entrypoint.py").write_text(ENTRYPOINT_PY)
        with open(workdir / "function.pkl", "wb") as f:
            cloudpickle.dump((self.func, args, kwargs), f)

    def build(self, *args, **kwargs):
        """Build a deployable Docker image locally."""
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
        """Deploy the function to a remote build server."""
        import requests

        port = kwargs.pop('port', 8080)
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

            print("Uploading build context...")
            try:
                with open(archive_path, 'rb') as f:
                    response = requests.post(
                        f"{self.base_url}/v1/deploy",
                        data={"function_name": self.name, "port": port},
                        files={'source_archive': (archive_name, f, 'application/gzip')},
                        headers={"X-API-Key": self.api_key},
                        timeout=9000
                    )
                response.raise_for_status()
                result = response.json()
                print(f"Deployed: {result['url']}")
                return result['url']

            except requests.exceptions.HTTPError as e:
                print(f"Deploy failed: {e.response.status_code}")
                try:
                    print(f"  {e.response.json()['detail']}")
                except:
                    print(f"  {e.response.text}")
                return None
            except requests.exceptions.RequestException as e:
                print(f"Connection error: {e}")
                return None

    def __del__(self):
        """Cleanup on garbage collection."""
        self._cleanup_container()
