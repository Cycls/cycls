from . import function as _function_module
from .function import function, Function
from .app import app, App
from .state import State, KV, SQL, FS, connect as connect_state

def __getattr__(name):
    if name in ("api_key", "base_url"):
        return getattr(_function_module, name)
    raise AttributeError(f"module 'cycls' has no attribute '{name}'")

def __setattr__(name, value):
    if name in ("api_key", "base_url"):
        setattr(_function_module, name, value)
    else:
        raise AttributeError(f"module 'cycls' has no attribute '{name}'")
