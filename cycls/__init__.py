try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from .function import function, Function, Image
from .function.remote import remote, local_entrypoint, RemoteError
from .app import app, App, Clerk, GCP, JWT, User, Sandbox, SandboxResult, DB, Workspace
from .agent.web import Web
from .agent import LLM, MCP, agent, Agent, events, to_ui
from .agent.logs import log

# Module-level config
api_key = None
base_url = None
