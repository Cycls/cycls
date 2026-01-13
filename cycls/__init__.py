import sys
from types import ModuleType
from .app import app
from .function import function
from .agent import agent
from .runtime import Runtime

class _Module(ModuleType):
    def __getattr__(self, name):
        from . import app as app_module
        if name in ("api_key", "base_url"):
            return getattr(app_module, name)
        raise AttributeError(f"module 'cycls' has no attribute '{name}'")

    def __setattr__(self, name, value):
        from . import app as app_module
        if name in ("api_key", "base_url"):
            setattr(app_module, name, value)
            return
        super().__setattr__(name, value)

sys.modules[__name__].__class__ = _Module
