from .sdk import Agent, function, agent, AgentRuntime
from .sdk import api_key, base_url
from .runtime import Runtime

# Re-export for module-level assignment (cycls.api_key = "...")
def __getattr__(name):
    if name == "api_key":
        from . import sdk
        return sdk.api_key
    if name == "base_url":
        from . import sdk
        return sdk.base_url
    raise AttributeError(f"module 'cycls' has no attribute '{name}'")

def __setattr__(name, value):
    if name == "api_key":
        from . import sdk
        sdk.api_key = value
        return
    if name == "base_url":
        from . import sdk
        sdk.base_url = value
        return
    raise AttributeError(f"module 'cycls' has no attribute '{name}'")