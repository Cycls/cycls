import docker
import cloudpickle
import tempfile
import hashlib
import os
import sys
import shutil
from pathlib import Path
from contextlib import contextmanager
import tarfile

# --- Top-Level Helper Functions ---

def _bootstrap_script(payload_file: str, result_file: str) -> str:
    """Generates the Python script that runs inside the Docker container."""
    return f"""
import cloudpickle
import sys
import os
import traceback
from pathlib import Path

if __name__ == "__main__":
    io_dir = Path(sys.argv[1])
    payload_path = io_dir / '{payload_file}'
    result_path = io_dir / '{result_file}'

    try:
        with open(payload_path, 'rb') as f:
            func, args, kwargs = cloudpickle.load(f)

        result = func(*args, **kwargs)

        with open(result_path, 'wb') as f:
            cloudpickle.dump(result, f)

    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
"""

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

# --- Main Runtime Class ---

class Runtime:
    """
    Handles building a Docker image and executing a function within a container.
    """
    def __init__(self, func, name, python_version=None, pip_packages=None, apt_packages=None, run_commands=None, copy=None, base_url=None, api_key=None):
        self.func = func
        self.python_version = python_version or f"{sys.version_info.major}.{sys.version_info.minor}"
        self.pip_packages = sorted(pip_packages or [])
        self.apt_packages = sorted(apt_packages or [])
        self.run_commands = sorted(run_commands or [])
        self.copy = copy or {}
        self.name = name
        self.base_url = base_url or "https://service-core-280879789566.me-central1.run.app"
        self.image_prefix = f"cycls/{name}"

        # Standard paths and filenames used inside the container
        self.io_dir = "/app/io"
        self.runner_filename = "runner.py"
        self.runner_path = f"/app/{self.runner_filename}"
        self.payload_file = "payload.pkl"
        self.result_file = "result.pkl"

        self.runner_script = _bootstrap_script(self.payload_file, self.result_file)
        self.tag = self._generate_base_tag()

        self.api_key = api_key
        self._docker_client = None
        self.managed_label = f"cycls.runtime"

    @property
    def docker_client(self):
        """
        Lazily initializes and returns a Docker client.
        This ensures Docker is only required for methods that actually use it.
        """
        if self._docker_client is None:
            try:
                print("🐳 Initializing Docker client...")
                client = docker.from_env()
                client.ping()
                self._docker_client = client
            except docker.errors.DockerException:
                print("\n❌ Error: Docker is not running or is not installed.")
                print("   This is required for local 'run' and 'build' operations.")
                print("   Please start the Docker daemon and try again.")
                sys.exit(1)
        return self._docker_client
    
    # docker system prune -af
    def _perform_auto_cleanup(self):
        """Performs a simple, automatic cleanup of old Docker resources."""
        try:
            for container in self.docker_client.containers.list(all=True, filters={"label": self.managed_label}):
                container.remove(force=True)

            cleaned_images = 0
            for image in self.docker_client.images.list(all=True, filters={"label": self.managed_label}):
                is_current = self.tag in image.tags
                is_deployable = any(t.startswith(f"{self.image_prefix}:deploy-") for t in image.tags)

                if not is_current and not is_deployable:
                    self.docker_client.images.remove(image.id, force=True)
                    cleaned_images += 1
            
            if cleaned_images > 0:
                print(f"🧹 Cleaned up {cleaned_images} old image version(s).")

            self.docker_client.images.prune(filters={'label': self.managed_label})

        except Exception as e:
            print(f"⚠️  An error occurred during cleanup: {e}")

    def _generate_base_tag(self) -> str:
        """Creates a unique tag for the base Docker image based on its dependencies."""
        signature_parts = [
            "".join(self.python_version),
            "".join(self.pip_packages),
            "".join(self.apt_packages),
            "".join(self.run_commands),
            self.runner_script
        ]
        for src, dst in sorted(self.copy.items()):
            if not Path(src).exists():
                raise FileNotFoundError(f"Path in 'copy' not found: {src}")
            content_hash = _hash_path(src)
            signature_parts.append(f"copy:{src}>{dst}:{content_hash}")

        signature = "".join(signature_parts)
        image_hash = hashlib.sha256(signature.encode()).hexdigest()
        return f"{self.image_prefix}:{image_hash[:16]}"

    def _generate_dockerfile(self, port=None) -> str:
        """Generates a multi-stage Dockerfile string."""
        run_pip_install = f"RUN pip install --no-cache-dir cloudpickle {' '.join(self.pip_packages)}"
        run_apt_install = (
            f"RUN apt-get update && apt-get install -y --no-install-recommends {' '.join(self.apt_packages)}"
            if self.apt_packages else ""
        )
        run_shell_commands = "\n".join([f"RUN {cmd}" for cmd in self.run_commands]) if self.run_commands else ""
        copy_lines = "\n".join([f"COPY context_files/{dst} {dst}" for dst in self.copy.values()])
        expose_line = f"EXPOSE {port}" if port else ""

        return f"""
# STAGE 1: Base image with all dependencies
FROM python:{self.python_version}-slim as base
ENV PIP_ROOT_USER_ACTION=ignore
ENV PYTHONUNBUFFERED=1
RUN mkdir -p {self.io_dir}
{run_apt_install}
{run_pip_install}
{run_shell_commands}
WORKDIR app
{copy_lines}
COPY {self.runner_filename} {self.runner_path}
ENTRYPOINT ["python", "{self.runner_path}", "{self.io_dir}"]

# STAGE 2: Final deployable image with the payload "baked in"
FROM base
{expose_line}
COPY {self.payload_file} {self.io_dir}/
"""

    def _prepare_build_context(self, workdir: Path, include_payload=False, args=None, kwargs=None):
        """Prepares a complete build context in the given directory."""
        port = kwargs.get('port') if kwargs else None
        
        # Create a dedicated subdirectory for all user-copied files
        context_files_dir = workdir / "context_files"
        context_files_dir.mkdir()

        if self.copy:
            for src, dst in self.copy.items():
                src_path = Path(src).resolve() # Resolve to an absolute path
                dest_in_context = context_files_dir / dst
                _copy_path(src_path, dest_in_context)

        (workdir / "Dockerfile").write_text(self._generate_dockerfile(port=port))
        (workdir / self.runner_filename).write_text(self.runner_script)

        if include_payload:
            payload_bytes = cloudpickle.dumps((self.func, args or [], kwargs or {}))
            (workdir / self.payload_file).write_bytes(payload_bytes)

    def _build_image_if_needed(self):
        """Checks if the base Docker image exists locally and builds it if not."""
        try:
            self.docker_client.images.get(self.tag)
            print(f"✅ Found cached base image: {self.tag}")
            return
        except docker.errors.ImageNotFound:
            print(f"🛠️  Building new base image: {self.tag}")

        with tempfile.TemporaryDirectory() as tmpdir_str:
            tmpdir = Path(tmpdir_str)
            # Prepare context without payload for the base image
            self._prepare_build_context(tmpdir)
            
            print("--- 🐳 Docker Build Logs (Base Image) ---")
            response_generator = self.docker_client.api.build(
                path=str(tmpdir),
                tag=self.tag,
                forcerm=True,
                decode=True,
                target='base', # Only build the 'base' stage
                labels={self.managed_label: "true"}, # image label
            )
            try:
                for chunk in response_generator:
                    if 'stream' in chunk:
                        print(chunk['stream'].strip())
                print("----------------------------------------")
                print(f"✅ Base image built successfully: {self.tag}")
            except docker.errors.BuildError as e:
                print(f"\n❌ Docker build failed. Reason: {e}")
                raise

    @contextmanager
    def runner(self, *args, **kwargs):
        """Context manager to set up, run, and tear down the container for local execution."""
        port = kwargs.get('port', None)
        self._perform_auto_cleanup()
        self._build_image_if_needed()
        container = None
        ports_mapping = {f'{port}/tcp': port} if port else None

        with tempfile.TemporaryDirectory() as tmpdir_str:
            tmpdir = Path(tmpdir_str)
            payload_path = tmpdir / self.payload_file
            result_path = tmpdir / self.result_file

            with payload_path.open('wb') as f:
                cloudpickle.dump((self.func, args, kwargs), f)

            try:
                container = self.docker_client.containers.create(
                    image=self.tag,
                    volumes={str(tmpdir): {'bind': self.io_dir, 'mode': 'rw'}},
                    ports=ports_mapping,
                    labels={self.managed_label: "true"} # container label
                )
                container.start()
                yield container, result_path
            finally:
                if container:
                    print("\n🧹 Cleaning up container...")
                    try:
                        container.stop(timeout=5)
                        container.remove()
                        print("✅ Container stopped and removed.")
                    except docker.errors.APIError as e:
                        print(f"⚠️  Could not clean up container: {e}")

    def run(self, *args, **kwargs):
        """Executes the function in a new Docker container and waits for the result."""
        print(f"🚀 Running function '{self.name}' in container...")
        try:
            with self.runner(*args, **kwargs) as (container, result_path):
                print("--- 🪵 Container Logs (streaming) ---")
                for chunk in container.logs(stream=True, follow=True):
                    print(chunk.decode('utf-8').strip())
                print("------------------------------------")

                result_status = container.wait()
                if result_status['StatusCode'] != 0:
                    print(f"\n❌ Error: Container exited with code: {result_status['StatusCode']}")
                    return None
                
                if result_path.exists():
                    with result_path.open('rb') as f:
                        result = cloudpickle.load(f)
                    print("✅ Function executed successfully.")
                    return result
                else:
                    print("\n❌ Error: Result file not found.")
                    return None
        except (KeyboardInterrupt, docker.errors.DockerException) as e:
            print(f"\n🛑 Operation stopped: {e}")
            return None

    def build(self, *args, **kwargs):
        """Builds a self-contained, deployable Docker image locally."""
        print("📦 Building self-contained image for deployment...")
        payload_hash = hashlib.sha256(cloudpickle.dumps((self.func, args, kwargs))).hexdigest()[:16]
        final_tag = f"{self.image_prefix}:deploy-{payload_hash}"

        try:
            self.docker_client.images.get(final_tag)
            print(f"✅ Found cached deployable image: {final_tag}")
            return final_tag
        except docker.errors.ImageNotFound:
            print(f"🛠️  Building new deployable image: {final_tag}")

        with tempfile.TemporaryDirectory() as tmpdir_str:
            tmpdir = Path(tmpdir_str)
            self._prepare_build_context(tmpdir, include_payload=True, args=args, kwargs=kwargs)

            print("--- 🐳 Docker Build Logs (Final Image) ---")
            response_generator = self.docker_client.api.build(
                path=str(tmpdir), tag=final_tag, forcerm=True, decode=True
            )
            try:
                for chunk in response_generator:
                    if 'stream' in chunk:
                        print(chunk['stream'].strip())
                print("-----------------------------------------")
                print(f"✅ Image built successfully: {final_tag}")
                port = kwargs.get('port') if kwargs else None
                print(f"🤖 Run: docker run --rm -d -p {port}:{port} {final_tag}")
                return final_tag
            except docker.errors.BuildError as e:
                print(f"\n❌ Docker build failed. Reason: {e}")
                return None

    def deploy(self, *args, **kwargs):
        """Deploys the function by sending it to a remote build server."""
        import requests

        print(f"🚀 Preparing to deploy function '{self.name}'")

        # 1. Prepare the build context and compress it into a tarball
        payload_hash = hashlib.sha256(cloudpickle.dumps((self.func, args, kwargs))).hexdigest()[:16]
        archive_name = f"source-{self.tag.split(':')[1]}-{payload_hash}.tar.gz"

        with tempfile.TemporaryDirectory() as tmpdir_str:
            tmpdir = Path(tmpdir_str)
            self._prepare_build_context(tmpdir, include_payload=True, args=args, kwargs=kwargs)
            
            archive_path = Path(tmpdir_str) / archive_name
            with tarfile.open(archive_path, "w:gz") as tar:
                # Add all files from the context to the tar archive
                for f in tmpdir.glob("**/*"):
                    if f.is_file():
                        tar.add(f, arcname=f.relative_to(tmpdir))
            
            # 2. Prepare the request payload
            port = kwargs.get('port', 8080)
            data_payload = {
                "function_name": self.name,
                "port": port,
                # "memory": "1Gi" # You could make this a parameter
            }
            headers = {
                "X-API-Key": self.api_key
            }

            # 3. Upload to the deploy server
            print("📦 Uploading build context to the deploy server...")
            try:
                with open(archive_path, 'rb') as f:
                    files = {'source_archive': (archive_name, f, 'application/gzip')}
                    
                    response = requests.post(
                        f"{self.base_url}/v1/deploy",
                        data=data_payload,
                        files=files,
                        headers=headers,
                        timeout=5*1800 # Set a long timeout for the entire process
                    )

                # 4. Handle the server's response
                response.raise_for_status() # Raise an exception for 4xx/5xx errors
                result = response.json()
                
                print(f"✅ Deployment successful!")
                print(f"🔗 Service is available at: {result['url']}")
                return result['url']

            except requests.exceptions.HTTPError as e:
                print(f"❌ Deployment failed. Server returned error: {e.response.status_code}")
                try:
                    # Try to print the detailed error message from the server
                    print(f"   Reason: {e.response.json()['detail']}")
                except:
                    print(f"   Reason: {e.response.text}")
                return None
            except requests.exceptions.RequestException as e:
                print(f"❌ Could not connect to the deploy server: {e}")
                return None

    def Deploy(self, *args, **kwargs):
        try:
            from .shared import upload_file_to_cloud, build_and_deploy_to_cloud
        except ImportError:
            print("❌ Shared not found. This is an internal method.")
            return None

        port = kwargs.get('port', 8080)
        
        with tempfile.TemporaryDirectory() as tmpdir_str:
            tmpdir = Path(tmpdir_str)
            self._prepare_build_context(tmpdir, include_payload=True, args=args, kwargs=kwargs)
            
            archive_path = Path(tmpdir_str) / "source.tar.gz"
            with tarfile.open(archive_path, "w:gz") as tar:
                for f in tmpdir.glob("**/*"):
                    if f.is_file():
                        tar.add(f, arcname=f.relative_to(tmpdir))

            archive_name = upload_file_to_cloud(self.name, archive_path)

        try:
            service = build_and_deploy_to_cloud(
            function_name=self.name,
            gcs_object_name=archive_name,
            port=port,
            memory="1Gi"
            )
        except Exception as e:
            print(f"❌ Cloud Deployment Failed: {e}")
            return None