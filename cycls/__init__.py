import sys
from types import ModuleType
from .sdk import function, agent
from .runtime import Runtime

class _Module(ModuleType):
    def __getattr__(self, name):
        from . import sdk
        if name in ("api_key", "base_url"):
            return getattr(sdk, name)
        raise AttributeError(f"module 'cycls' has no attribute '{name}'")

    def __setattr__(self, name, value):
        from . import sdk
        if name in ("api_key", "base_url"):
            setattr(sdk, name, value)
            return
        super().__setattr__(name, value)

sys.modules[__name__].__class__ = _Module
