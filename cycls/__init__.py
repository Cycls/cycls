from .sdk import function, agent
from .runtime import Runtime

def __getattr__(name):
    from . import sdk
    if name in ("api_key", "base_url"):
        return getattr(sdk, name)
    raise AttributeError(f"module 'cycls' has no attribute '{name}'")

def __setattr__(name, value):
    from . import sdk
    if name in ("api_key", "base_url"):
        setattr(sdk, name, value)
        return
    raise AttributeError(f"module 'cycls' has no attribute '{name}'")
