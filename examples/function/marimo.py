import cycls
import os

@cycls.function(pip=["marimo"])
def marimo_notebook(port):
    """
    Runs a Marimo notebook server in a containerized environment.
    """
    # WARNING: Disabling authentication is insecure and should not be done in production.
    command = f"marimo edit --host 0.0.0.0 --port {port} --no-token"

    print(f"Starting Marimo notebook server at http://localhost:{port}")
    os.system(command)

marimo_notebook.run(port=8080)
