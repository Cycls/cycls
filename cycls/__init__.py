import sys
import importlib
from types import ModuleType
from .function import function, Function
from .app import app, App

def _get_function_module():
    return importlib.import_module('cycls.function')

class _Module(ModuleType):
    def __getattr__(self, name):
        if name in ("api_key", "base_url"):
            return getattr(_get_function_module(), name)
        raise AttributeError(f"module 'cycls' has no attribute '{name}'")

    def __setattr__(self, name, value):
        if name in ("api_key", "base_url"):
            setattr(_get_function_module(), name, value)
            return
        super().__setattr__(name, value)

sys.modules[__name__].__class__ = _Module
