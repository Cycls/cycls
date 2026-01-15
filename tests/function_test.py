import pytest
import cycls
import requests
import time

# This is the main test file for the 'cycls' library.
# To run these tests, install dependencies:
# poetry install --with test
#
# Then, from your project's root directory, simply run:
# poetry run pytest tests/ -v -s


# --- Test Case 1: Short-Lived Task ---
# This test verifies the core functionality: running a simple function
# that takes an argument, performs a calculation, and returns a result.

def test_short_lived_task_with_return_value():
    """
    Tests a basic function that should execute and return a value.
    """
    print("\n--- Running test: test_short_lived_task_with_return_value ---")
    # 1. Define the agent and the function to be containerized.
    #    This agent will have 'numpy' installed in its environment.
    @cycls.function(pip=["numpy"])
    def square_number(x):
        import numpy as np
        # The function prints to stdout inside the container and returns a value.
        print(f"Squaring the number: {x}")
        return np.square(x).tolist()

    # 2. Execute the function.
    result = square_number.run(7)

    # 3. Assert that the returned result is correct.
    assert result == 49
    print("✅ Test passed.")


# --- Test Case 2: Long-Running Service ---
# This test verifies that a long-running service (like a web server)
# can be started and can correctly respond to network requests.

def test_long_running_service():
    """
    Tests a long-running web service started with a port mapping.
    """
    print("\n--- Running test: test_long_running_service ---")
    # 1. Define the agent and the web service function.
    #    We use a non-standard port to avoid conflicts with other services.
    TEST_PORT = 8999
    
    @cycls.function(pip=["fastapi", "uvicorn"])
    def simple_web_server(port):
        from fastapi import FastAPI
        import uvicorn

        app = FastAPI()

        @app.get("/")
        def root():
            return {"status": "ok", "message": "Service is running!"}

        # The server must listen on 0.0.0.0 to be accessible from the host.
        uvicorn.run(app, host="0.0.0.0", port=port)


    # 2. Use the context manager to run the service.
    #    The `with` block handles the entire lifecycle: start, wait, and cleanup.
    try:
        with simple_web_server.runner(port=TEST_PORT) as (container, _):
            print(f"✅ Context manager confirmed service is live in container {container.short_id}.")
            
            time.sleep(5)

            # 3. Make the HTTP request to the now-guaranteed-to-be-running service.
            print(f"Making request to http://localhost:{TEST_PORT}")
            response = requests.get(f"http://localhost:{TEST_PORT}", timeout=10)

            # 4. Assert that the response from the service is correct.
            assert response.status_code == 200
            assert response.json() == {"status": "ok", "message": "Service is running!"}
            print("✅ Test passed.")

    except (requests.ConnectionError, RuntimeError) as e:
        print(f"❌ Test failed: Could not connect to the service. Error: {e}")
        # Re-raise the exception to make the test framework aware of the failure.
        raise


# --- Test Case 3: APT Package Installation ---
# This test verifies that apt packages (like a C compiler) can be installed
# and used to perform tasks within the container.

def test_apt_package_installation():
    """
    Tests that apt packages can be installed and used.
    """
    print("\n--- Running test: test_apt_package_installation ---")
    # 1. Define the C code and the expected output from running it.
    c_code = r"""
    #include <stdio.h>
    #include <stdlib.h>
    int main(){int i,j;for(i=10;i>=1;--i){for(j=1;j<=i;++j){printf("*");}printf("\n");}return 0;}
    """
    expected_output = "\n".join("*" * i for i in range(10, 0, -1))

    # 2. Define the agent that will compile and run the C code.
    #    It needs 'gcc' to compile and 'libc6-dev' for standard libraries.
    @cycls.function(apt=["gcc", "libc6-dev"])
    def compile_and_run_c_code():
        import subprocess

        # Write the C code to a file inside the container.
        with open("triangle.c", "w") as f:
            f.write(c_code)

        # Compile the C code using the installed gcc.
        subprocess.run(["gcc", "triangle.c", "-o", "triangle_app"], check=True)

        # Run the compiled executable and capture its output.
        result = subprocess.run(
            ["./triangle_app"], check=True, capture_output=True, text=True
        )
        return result.stdout.strip()

    # 3. Execute the function remotely.
    actual_output = compile_and_run_c_code.run()

    # 4. Assert that the output from the C program is correct.
    assert actual_output == expected_output
    print("✅ Test passed.")


# --- Test Case 4: Copy Local Directory ---
# This test verifies that a local directory can be copied into the
# container and its files can be accessed.

def test_copy_local_directory():
    """
    Tests that a local directory can be copied into the container.
    """
    print("\n--- Running test: test_copy_local_directory ---")
    # 1. Define the agent that will analyze the sales data.
    #    - `pip=["pandas"]`: Installs the pandas library.
    #    - `copy=["tests/data"]`: Copies the local 'tests/data' directory
    #      into the container (pytest runs from project root).
    @cycls.function(pip=["pandas"], copy=["tests/data"])
    def analyze_sales():
        import pandas as pd
        # The path inside the container mirrors the source structure.
        df = pd.read_csv("tests/data/sales_data.csv")
        total_revenue = df['revenue'].sum()
        return f"Total revenue: ${total_revenue}"

    # 2. Execute the function remotely.
    result = analyze_sales.run()

    # 3. Assert that the result is correct.
    assert result == "Total revenue: $520"
    print("✅ Test passed.")


# --- Test Case 5: Copy File Collision ---
# This test verifies that copying multiple files with the same name
# from different directories doesn't cause collisions.

def test_copy_file_collision():
    """
    Tests that files with the same name in different directories are preserved.
    """
    print("\n--- Running test: test_copy_file_collision ---")
    # 1. Copy two config.txt files from different directories.
    #    Both should be preserved with their directory structure.
    @cycls.function(copy=["tests/data/dev/config.txt", "tests/data/prod/config.txt"])
    def check_for_collision():
        with open("tests/data/dev/config.txt", "r") as f:
            dev_content = f.read().strip()
        with open("tests/data/prod/config.txt", "r") as f:
            prod_content = f.read().strip()
        return {"dev": dev_content, "prod": prod_content}

    # 2. Execute the function.
    result = check_for_collision.run()

    # 3. Assert both files have distinct content (no collision).
    assert result == {"dev": "dev", "prod": "prod"}
    print("✅ Test passed.")


# --- Test Case 6: Run Commands ---
# This test verifies that custom shell commands can be executed
# during the Docker image build process.

def test_run_commands():
    """
    Tests that run_commands executes shell commands during build.
    """
    print("\n--- Running test: test_run_commands ---")
    # 1. Define a function that uses run_commands to create a file during build.
    #    The function then reads that file to verify it was created.
    @cycls.function(run_commands=["echo 'hello from build' > /app/build_marker.txt"])
    def check_build_marker():
        with open("/app/build_marker.txt", "r") as f:
            return f.read().strip()

    # 2. Execute the function.
    result = check_build_marker.run()

    # 3. Assert that the file created during build contains the expected content.
    assert result == "hello from build"
    print("✅ Test passed.")


# --- Test Case 7: Build Deployable Image ---
# This test verifies that .build() creates a standalone Docker image
# that can run without gRPC, using a baked-in pickled function.

def test_build_deployable_image():
    """
    Tests that .build() creates a working standalone Docker image.
    """
    import subprocess
    print("\n--- Running test: test_build_deployable_image ---")

    TEST_PORT = 8998
    CONTAINER_NAME = "test-build-deploy"

    # 1. Define a FastAPI service function.
    @cycls.function(pip=["fastapi", "uvicorn"])
    def build_test_service(port):
        from fastapi import FastAPI
        import uvicorn

        app = FastAPI()

        @app.get("/")
        def root():
            return {"status": "ok", "source": "built-image"}

        uvicorn.run(app, host="0.0.0.0", port=port)

    # 2. Build the deployable image (bakes in port arg).
    image_tag = build_test_service.build(port=TEST_PORT)
    assert image_tag is not None
    assert ":deploy-" in image_tag
    print(f"✅ Built image: {image_tag}")

    try:
        # 3. Run the built image directly with docker (no gRPC).
        subprocess.run(
            ["docker", "run", "-d", "--rm", "-p", f"{TEST_PORT}:{TEST_PORT}",
             "--name", CONTAINER_NAME, image_tag],
            check=True, capture_output=True
        )
        print(f"✅ Started container: {CONTAINER_NAME}")

        # 4. Wait for service to start and make request.
        time.sleep(3)
        response = requests.get(f"http://localhost:{TEST_PORT}", timeout=10)

        # 5. Assert response is correct.
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "source": "built-image"}
        print("✅ Test passed.")

    finally:
        # 6. Cleanup: stop container.
        subprocess.run(["docker", "stop", CONTAINER_NAME], capture_output=True)
        print(f"✅ Cleaned up container: {CONTAINER_NAME}")
