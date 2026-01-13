"""Function module - containerized Python functions."""

import os
from .runtime import Runtime

# Import config from app module
def _get_api_key():
    from . import app as app_module
    return app_module.api_key or os.getenv("CYCLS_API_KEY")

def _get_base_url():
    from . import app as app_module
    return app_module.base_url or os.getenv("CYCLS_BASE_URL")


def function(python_version=None, pip=None, apt=None, run_commands=None, copy=None, name=None):
    """Decorator that transforms a Python function into a containerized, remotely executable object."""
    def decorator(func):
        func_name = name or func.__name__
        copy_dict = {i: i for i in copy or []}
        return Runtime(func, func_name.replace('_', '-'), python_version, pip, apt, run_commands, copy_dict, _get_base_url(), _get_api_key())
    return decorator
