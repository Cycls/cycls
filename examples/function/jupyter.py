import cycls
import os

@cycls.function(pip=["jupyter"])
def jupyter_notebook(port):
    """
    Runs a Jupyter Notebook server in a containerized environment.
    """
    # WARNING: Disabling authentication is insecure and should not be done in production.
    command = (
        f"jupyter notebook --ip=0.0.0.0 --port={port} --allow-root "
        "--NotebookApp.token='' --NotebookApp.password=''"
    )

    print(f"Starting Jupyter Notebook server at http://localhost:{port}")
    os.system(command)

# This is the entry point that cycls will execute.
# It runs the function defined above and forwards port 8888 from the
# remote environment to your local machine.
jupyter_notebook.run(port=8888)
# jupyter_notebook.deploy(port=8888)

# jupyter_notebook.deploy(server_url="...", api_key="...", port=8888)