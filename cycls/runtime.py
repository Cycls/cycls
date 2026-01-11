import docker
import cloudpickle
import tempfile
import hashlib
import os
import sys
import shutil
from pathlib import Path
import tarfile
import time

from .grpc import RuntimeClient

# Enable BuildKit for faster builds with better caching
os.environ["DOCKER_BUILDKIT"] = "1"

# gRPC port for container communication
GRPC_PORT = 50051

def _hash_path(path_str: str) -> str:
    """Hashes a file or a directory's contents to create a deterministic signature."""
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
                relpath = filepath.relative_to(p)
                h.update(str(relpath).encode())
                with filepath.open('rb') as f:
                    while chunk := f.read(65536):
                        h.update(chunk)
    return h.hexdigest()

def _copy_path(src_path: Path, dest_path: Path):
    """Recursively copies a file or directory to a destination path."""
    if src_path.is_dir():
        shutil.copytree(src_path, dest_path, dirs_exist_ok=True)
    else:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src_path, dest_path)

# Pre-built base image with common dependencies
BASE_IMAGE = "ghcr.io/cycls/base:python3.12"
BASE_PACKAGES = {
    "cloudpickle", "cryptography", "fastapi", "fastapi[standard]",
    "pydantic", "pyjwt", "uvicorn", "uvicorn[standard]", "httpx"
}

# Packages required for gRPC runtime (always installed)
GRPC_PACKAGES = {"grpcio", "protobuf"}


class Runtime:
    """
    Handles building a Docker image and executing a function within a container via gRPC.
    """
    def __init__(self, func, name, python_version=None, pip_packages=None, apt_packages=None, run_commands=None, copy=None, base_url=None, api_key=None, base_image=None):
        self.func = func
        self.python_version = python_version or f"{sys.version_info.major}.{sys.version_info.minor}"
        self.apt_packages = sorted(apt_packages or [])
        self.run_commands = sorted(run_commands or [])
        self.copy = copy or {}
        self.name = name
        self.base_url = base_url or "https://service-core-280879789566.me-central1.run.app"
        self.image_prefix = f"cycls/{name}"

        # Use pre-built base image by default, filter out already-installed packages
        self.base_image = base_image or BASE_IMAGE
        all_pip = set(pip_packages or []) | GRPC_PACKAGES  # Always include gRPC
        self.pip_packages = sorted(all_pip - BASE_PACKAGES) if self.base_image == BASE_IMAGE else sorted(all_pip | {"cloudpickle"})

        # gRPC configuration
        self.grpc_port = GRPC_PORT
        self.tag = self._generate_base_tag()

        self.api_key = api_key
        self._docker_client = None
        self.managed_label = "cycls.runtime"

        # Warm container state
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

    def _perform_auto_cleanup(self):
        """Performs automatic cleanup of old Docker resources."""
        try:
            for container in self.docker_client.containers.list(all=True, filters={"label": self.managed_label}):
                if container.id != (self._container.id if self._container else None):
                    container.remove(force=True)

            cleaned_images = 0
            for image in self.docker_client.images.list(all=True, filters={"label": self.managed_label}):
                is_current = self.tag in image.tags
                is_deployable = any(t.startswith(f"{self.image_prefix}:deploy-") for t in image.tags)

                if not is_current and not is_deployable:
                    self.docker_client.images.remove(image.id, force=True)
                    cleaned_images += 1

            if cleaned_images > 0:
                print(f"Cleaned up {cleaned_images} old image(s).")

            self.docker_client.images.prune(filters={'label': self.managed_label})

        except Exception as e:
            print(f"Warning: cleanup error: {e}")

    def _generate_base_tag(self) -> str:
        """Creates a unique tag for the Docker image based on its dependencies."""
        signature_parts = [
            self.base_image,
            self.python_version,
            "".join(self.pip_packages),
            "".join(self.apt_packages),
            "".join(self.run_commands),
            "grpc-v1"
        ]
        for src, dst in sorted(self.copy.items()):
            if not Path(src).exists():
                raise FileNotFoundError(f"Path in 'copy' not found: {src}")
            content_hash = _hash_path(src)
            signature_parts.append(f"copy:{src}>{dst}:{content_hash}")

        signature = "".join(signature_parts)
        image_hash = hashlib.sha256(signature.encode()).hexdigest()
        return f"{self.image_prefix}:{image_hash[:16]}"

    def _generate_dockerfile(self, service_port=None) -> str:
        """Generates a Dockerfile for gRPC-based runtime."""
        using_base = self.base_image == BASE_IMAGE

        run_pip_install = (
            f"RUN uv pip install --system --no-cache {' '.join(self.pip_packages)}"
            if self.pip_packages else ""
        )
        run_apt_install = (
            f"RUN apt-get update && apt-get install -y --no-install-recommends {' '.join(self.apt_packages)}"
            if self.apt_packages else ""
        )
        run_shell_commands = "\n".join([f"RUN {cmd}" for cmd in self.run_commands]) if self.run_commands else ""
        copy_lines = "\n".join([f"COPY context_files/{dst} /app/{dst}" for dst in self.copy.values()])

        env_lines = "" if using_base else """ENV PIP_ROOT_USER_ACTION=ignore \\
    PYTHONUNBUFFERED=1
WORKDIR /app"""

        # Expose both gRPC port and optional service port
        expose_lines = f"EXPOSE {self.grpc_port}"
        if service_port:
            expose_lines += f" {service_port}"

        return f"""FROM {self.base_image}
{env_lines}
{run_apt_install}
{run_pip_install}
{run_shell_commands}
{copy_lines}
COPY grpc_runtime/ /app/grpc_runtime/
{expose_lines}
CMD ["python", "-m", "grpc_runtime.server", "--port", "{self.grpc_port}"]
"""

    def _prepare_build_context(self, workdir: Path, service_port=None):
        """Prepares a complete build context in the given directory."""
        context_files_dir = workdir / "context_files"
        context_files_dir.mkdir()

        if self.copy:
            for src, dst in self.copy.items():
                src_path = Path(src).resolve()
                dest_in_context = context_files_dir / dst
                _copy_path(src_path, dest_in_context)

        (workdir / "Dockerfile").write_text(self._generate_dockerfile(service_port=service_port))

        # Copy the gRPC runtime module
        grpc_src = Path(__file__).parent / "grpc"
        grpc_dest = workdir / "grpc_runtime"
        shutil.copytree(grpc_src, grpc_dest, ignore=shutil.ignore_patterns('*.proto', '__pycache__'))

    def _build_image_if_needed(self, service_port=None):
        """Checks if the Docker image exists locally and builds it if not."""
        try:
            self.docker_client.images.get(self.tag)
            print(f"Found cached image: {self.tag}")
            return
        except docker.errors.ImageNotFound:
            print(f"Building new image: {self.tag}")

        with tempfile.TemporaryDirectory() as tmpdir_str:
            tmpdir = Path(tmpdir_str)
            self._prepare_build_context(tmpdir, service_port=service_port)

            print("--- Docker Build Logs ---")
            response_generator = self.docker_client.api.build(
                path=str(tmpdir),
                tag=self.tag,
                forcerm=True,
                decode=True,
                labels={self.managed_label: "true"},
            )
            try:
                for chunk in response_generator:
                    if 'stream' in chunk:
                        print(chunk['stream'].strip())
                print("-------------------------")
                print(f"Image built: {self.tag}")
            except docker.errors.BuildError as e:
                print(f"\nDocker build failed: {e}")
                raise

    def _ensure_container(self, service_port=None):
        """Start container if not running, return gRPC client."""
        if self._client and self._container:
            # Check if container is still running
            try:
                self._container.reload()
                if self._container.status == 'running':
                    return self._client
            except:
                pass
            self._cleanup_container()

        self._perform_auto_cleanup()
        self._build_image_if_needed(service_port=service_port)

        # Build port mappings
        ports = {f'{self.grpc_port}/tcp': None}
        if service_port:
            ports[f'{service_port}/tcp'] = service_port

        self._container = self.docker_client.containers.run(
            self.tag,
            detach=True,
            ports=ports,
            labels={self.managed_label: "true"}
        )

        # Get assigned gRPC port
        self._container.reload()
        self._host_port = int(self._container.ports[f'{self.grpc_port}/tcp'][0]['HostPort'])

        # Wait for gRPC server to be ready
        print(f"Waiting for container...")
        self._client = RuntimeClient(port=self._host_port)
        for _ in range(30):
            if self._client.ping(timeout=1):
                print(f"Container ready on port {self._host_port}")
                return self._client
            time.sleep(0.2)

        raise RuntimeError("Container failed to start")

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
        service_port = kwargs.pop('port', None)
        print(f"Running '{self.name}'...")
        try:
            client = self._ensure_container(service_port=service_port)
            return client.call(self.func, *args, **kwargs)
        except Exception as e:
            print(f"Error: {e}")
            return None

    def stream(self, *args, **kwargs):
        """Execute the function and yield streamed results."""
        service_port = kwargs.pop('port', None)
        client = self._ensure_container(service_port=service_port)
        yield from client.execute(self.func, *args, **kwargs)

    def watch(self, *args, **kwargs):
        """Run with file watching - re-executes function on changes."""
        try:
            from watchfiles import watch as watchfiles_watch
        except ImportError:
            print("watchfiles not installed. Run: pip install watchfiles")
            return

        import inspect
        import subprocess

        main_script = None
        for frame_info in inspect.stack():
            filename = frame_info.filename
            if filename.endswith('.py') and not filename.startswith('<'):
                main_script = Path(filename).resolve()

        watch_paths = []
        if main_script and main_script.exists():
            watch_paths.append(main_script)
        watch_paths.extend([Path(src).resolve() for src in self.copy.keys() if Path(src).exists()])

        if not watch_paths:
            print("No files to watch.")
            return self.run(*args, **kwargs)

        print(f"Watching for changes:")
        for p in watch_paths:
            print(f"   {p}")
        print()

        while True:
            print(f"Running {main_script.name}...")
            proc = subprocess.Popen(
                [sys.executable, str(main_script)],
                env={**os.environ, '_CYCLS_WATCH_CHILD': '1'}
            )

            try:
                for changes in watchfiles_watch(*watch_paths):
                    changed_files = [str(c[1]) for c in changes]
                    print(f"\nChanges detected:")
                    for f in changed_files:
                        print(f"   {f}")
                    break

                print("\nRestarting...\n")
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()

            except KeyboardInterrupt:
                print("\nStopping...")
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                return

    def build(self, *args, **kwargs):
        """Build a deployable Docker image locally."""
        print("Building deployable image...")
        service_port = kwargs.get('port', 8080)

        # For deployed images, we need to bake in the function
        # Generate a tag based on function + deps
        func_hash = hashlib.sha256(cloudpickle.dumps(self.func)).hexdigest()[:16]
        final_tag = f"{self.image_prefix}:deploy-{func_hash}"

        try:
            self.docker_client.images.get(final_tag)
            print(f"Found cached image: {final_tag}")
            return final_tag
        except docker.errors.ImageNotFound:
            print(f"Building: {final_tag}")

        with tempfile.TemporaryDirectory() as tmpdir_str:
            tmpdir = Path(tmpdir_str)
            self._prepare_build_context(tmpdir, service_port=service_port)

            print("--- Docker Build Logs ---")
            response_generator = self.docker_client.api.build(
                path=str(tmpdir),
                tag=final_tag,
                forcerm=True,
                decode=True,
                labels={self.managed_label: "true"}
            )
            try:
                for chunk in response_generator:
                    if 'stream' in chunk:
                        print(chunk['stream'].strip())
                print("-------------------------")
                print(f"Image built: {final_tag}")
                print(f"Run: docker run --rm -p {service_port}:{service_port} {final_tag}")
                return final_tag
            except docker.errors.BuildError as e:
                print(f"\nBuild failed: {e}")
                return None

    def deploy(self, *args, **kwargs):
        """Deploy the function to a remote build server."""
        import requests

        print(f"Preparing to deploy '{self.name}'")
        service_port = kwargs.get('port', 8080)

        func_hash = hashlib.sha256(cloudpickle.dumps(self.func)).hexdigest()[:16]
        archive_name = f"source-{self.tag.split(':')[1]}-{func_hash}.tar.gz"

        with tempfile.TemporaryDirectory() as tmpdir_str:
            tmpdir = Path(tmpdir_str)
            self._prepare_build_context(tmpdir, service_port=service_port)

            archive_path = Path(tmpdir_str) / archive_name
            with tarfile.open(archive_path, "w:gz") as tar:
                for f in tmpdir.glob("**/*"):
                    if f.is_file():
                        tar.add(f, arcname=f.relative_to(tmpdir))

            data_payload = {
                "function_name": self.name,
                "port": service_port,
            }
            headers = {"X-API-Key": self.api_key}

            print("Uploading build context...")
            try:
                with open(archive_path, 'rb') as f:
                    files = {'source_archive': (archive_name, f, 'application/gzip')}
                    response = requests.post(
                        f"{self.base_url}/v1/deploy",
                        data=data_payload,
                        files=files,
                        headers=headers,
                        timeout=5*1800
                    )

                response.raise_for_status()
                result = response.json()

                print(f"Deployment successful!")
                print(f"Service URL: {result['url']}")
                return result['url']

            except requests.exceptions.HTTPError as e:
                print(f"Deployment failed: {e.response.status_code}")
                try:
                    print(f"   Reason: {e.response.json()['detail']}")
                except:
                    print(f"   Reason: {e.response.text}")
                return None
            except requests.exceptions.RequestException as e:
                print(f"Could not connect to deploy server: {e}")
                return None

    def __del__(self):
        """Cleanup on garbage collection."""
        self._cleanup_container()
