try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from .function import function, Function, Image
from .app import app, App, Clerk, JWT, User, Sandbox
from .agent.web import Web
from .app.db import DB
from .app.workspace import Workspace
from .agent import LLM, agent, Agent

# Module-level config
api_key = None
base_url = None
