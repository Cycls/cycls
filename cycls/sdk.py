from .runtime import Runtime

def function(python_version="3.12", pip_install=None, apt_install=None, run_commands=None, copy=None, name=None, base_url=None, api_key=None):
    # """
    # A decorator factory that transforms a Python function into a containerized,
    # remotely executable object.

    # Args:
    #     pip (list[str], optional): A list of pip packages to install.
    #     apt (list[str], optional): A list of apt packages to install.
    #     copy (list[str], optional): A list of local paths to copy to the
    #         same path inside the image. For static dependencies.
    #     name (str, optional): A name for this function. Defaults to the function's name.

    # Returns:
    #     A decorator that replaces the decorated function with a Runtime instance.
    # """
    def decorator(func):
        Name = name or func.__name__ # should be moved to runtime... or default?
        copy_dict = {i:i for i in copy or []}
        return Runtime(func, Name.replace('_', '-'), python_version, pip_install, apt_install, run_commands, copy_dict, base_url, api_key)
    return decorator