"""Agent module for @cycls.agent() - agentic experience with tools and skills."""

import os
import json
import uvicorn
from typing import Optional
from pathlib import Path

from .tools import DEFAULT_TOOLS, Tool, get_tool
from .skills import Skill, load_skills, discover_skills
from .models import get_client


DEFAULT_SYSTEM = """You are a helpful coding assistant with access to tools for reading, writing, and editing files, as well as running bash commands.

When working on tasks:
1. First understand what's being asked
2. Use tools to explore and understand the codebase
3. Make changes incrementally
4. Verify your changes work

Be concise in your responses. Focus on completing the task efficiently."""


class AgentContext:
    """Context object passed to agent hooks."""

    def __init__(self, messages: list[dict], user=None):
        self.messages = messages
        self.user = user
        self.system = None
        self.files = []

    def include(self, path: str):
        """Include a file's content in the context."""
        self.files.append(path)


async def run_agent_loop(
    messages: list[dict],
    model: str,
    tools: list[Tool],
    skills: list[Skill],
    system: str,
    max_turns: int = 50,
):
    """Run the agent loop - yields streaming chunks."""
    client = get_client(model)

    # Build tool schemas
    tool_schemas = [t.to_schema() for t in tools]

    # Add skill tools
    for skill in skills:
        tool_schemas.append(skill.to_tool_schema())

    # Build tool lookup
    tool_map = {t.name: t for t in tools}
    skill_map = {f"skill_{s.name.replace('-', '_')}": s for s in skills}

    conversation = list(messages)
    turns = 0

    while turns < max_turns:
        turns += 1

        # Collect full response before processing tool calls
        assistant_text = ""
        tool_calls = []

        async for chunk in client.stream(conversation, tool_schemas, system):
            if chunk["type"] == "text":
                assistant_text += chunk["text"]
                yield {"type": "text", "text": chunk["text"]}

            elif chunk["type"] == "tool_call":
                tool_calls.append(chunk)

            elif chunk["type"] == "error":
                yield {"type": "error", "error": chunk["error"]}
                return

            elif chunk["type"] == "done":
                break

        # If no tool calls, we're done
        if not tool_calls:
            return

        # Add assistant message with tool calls to conversation
        assistant_msg = {
            "role": "assistant",
            "content": assistant_text,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc["arguments"]),
                    }
                }
                for tc in tool_calls
            ]
        }
        conversation.append(assistant_msg)

        # Execute tool calls
        for tc in tool_calls:
            tool_name = tc["name"]
            tool_args = tc["arguments"]
            tool_id = tc["id"]

            yield {"type": "tool_call", "name": tool_name, "arguments": tool_args}

            # Check if it's a skill
            if tool_name in skill_map:
                skill = skill_map[tool_name]
                # Inject skill content as context
                result = f"[Skill: {skill.name}]\n\n{skill.content}\n\nTask: {tool_args.get('task', '')}"
                yield {"type": "tool_result", "name": tool_name, "result": "(skill activated)"}
            elif tool_name in tool_map:
                tool = tool_map[tool_name]
                result = tool.execute(**tool_args)
                # Truncate very long results
                if len(result) > 50000:
                    result = result[:50000] + "\n... (truncated)"
                yield {"type": "tool_result", "name": tool_name, "result": result[:500] + "..." if len(result) > 500 else result}
            else:
                result = f"Error: Unknown tool '{tool_name}'"
                yield {"type": "tool_result", "name": tool_name, "result": result}

            # Add tool result to conversation
            conversation.append({
                "role": "tool",
                "tool_call_id": tool_id,
                "content": result,
            })

    yield {"type": "error", "error": f"Max turns ({max_turns}) exceeded"}


async def agent_handler(context: AgentContext, model: str, tools: list[Tool], skills: list[Skill], system: str, hook=None):
    """Handler function for the agent - yields streaming chunks for the web layer."""
    # Run optional hook for customization
    if hook:
        hook(context)

    # Build system prompt
    full_system = system or DEFAULT_SYSTEM
    if context.system:
        full_system = context.system

    # Include any files
    for file_path in context.files:
        try:
            content = Path(file_path).read_text()
            full_system += f"\n\n--- {file_path} ---\n{content}"
        except:
            pass

    # Add skill descriptions to system
    if skills:
        full_system += "\n\n## Available Skills\n"
        for skill in skills:
            full_system += f"- {skill.name}: {skill.description}\n"

    async for chunk in run_agent_loop(
        messages=context.messages,
        model=model,
        tools=tools,
        skills=skills,
        system=full_system,
    ):
        if chunk["type"] == "text":
            yield chunk["text"]
        elif chunk["type"] == "tool_call":
            yield {"type": "status", "status": f"Using {chunk['name']}..."}
        elif chunk["type"] == "tool_result":
            yield {"type": "thinking", "thinking": f"{chunk['name']}: {chunk['result']}"}
        elif chunk["type"] == "error":
            yield {"type": "callout", "callout": chunk["error"], "style": "error"}


class AgentRuntime:
    """Wraps an agent with local/deploy capabilities."""

    def __init__(
        self,
        name: str,
        model: str,
        tools: list[Tool],
        skills: list[Skill],
        system: str,
        hook,
        pip: list[str],
        apt: list[str],
        theme: str,
        auth: bool,
        analytics: bool,
    ):
        self.name = name
        self.model = model
        self.tools = tools
        self.skills = skills
        self.system = system
        self.hook = hook
        self.pip = pip
        self.apt = apt
        self.theme = theme
        self.auth = auth
        self.analytics = analytics

    async def _handler(self, context):
        """Internal handler that wraps agent_handler."""
        agent_context = AgentContext(context.messages, getattr(context, 'user', None))
        async for chunk in agent_handler(
            agent_context,
            self.model,
            self.tools,
            self.skills,
            self.system,
            self.hook,
        ):
            yield chunk

    def local(self, port=8080):
        """Run locally for development."""
        from .sdk import _resolve_theme, _set_prod, CYCLS_PATH
        from .web import web, Config
        from .auth import PK_TEST, JWKS_TEST

        theme = _resolve_theme(self.theme)
        config = Config(
            auth=self.auth,
            analytics=self.analytics,
            header=f"Agent: {self.name}",
            intro="",
            title=self.name,
            plan="free",
            org=None,
            public_path=str(theme),
            prod=False,
            pk=PK_TEST,
            jwks=JWKS_TEST,
        )

        print(f"Starting agent '{self.name}' at localhost:{port}")
        print(f"Model: {self.model}")
        print(f"Tools: {[t.name for t in self.tools]}")
        if self.skills:
            print(f"Skills: {[s.name for s in self.skills]}")

        uvicorn.run(web(self._handler, config), host="0.0.0.0", port=port)

    def deploy(self):
        """Deploy to production."""
        raise NotImplementedError("Agent deployment coming soon")


def agent(
    model: str,
    name: str = None,
    tools: list[str] = None,
    skills: list[str] = None,
    system: str = None,
    pip: list[str] = None,
    apt: list[str] = None,
    theme: str = "default",
    auth: bool = False,
    analytics: bool = False,
):
    """Decorator that creates a deployable agent with tools and skills.

    Args:
        model: Model to use (e.g., "anthropic/claude-sonnet-4", "openai/gpt-4o")
        name: Agent name (defaults to function name)
        tools: List of tool names to enable (defaults to all)
        skills: List of skill paths to load
        system: Custom system prompt
        pip: Additional pip packages
        apt: Additional apt packages
        theme: UI theme
        auth: Enable authentication
        analytics: Enable analytics

    Example:
        @cycls.agent(model="anthropic/claude-sonnet-4")
        def my_agent():
            pass

        my_agent.local()
    """
    pip = pip or []
    apt = apt or []

    # Resolve tools
    if tools is None:
        agent_tools = list(DEFAULT_TOOLS)
    else:
        agent_tools = [get_tool(t) for t in tools if get_tool(t)]

    # Load skills
    agent_skills = []
    if skills:
        agent_skills = load_skills(skills)
    else:
        # Auto-discover from .cycls/skills/
        agent_skills = discover_skills()

    def decorator(func):
        agent_name = name or func.__name__.replace('_', '-')

        # The function can be a hook for customization
        hook = func if func.__code__.co_argcount > 0 else None

        return AgentRuntime(
            name=agent_name,
            model=model,
            tools=agent_tools,
            skills=agent_skills,
            system=system,
            hook=hook,
            pip=["httpx", *pip],
            apt=apt,
            theme=theme,
            auth=auth,
            analytics=analytics,
        )

    return decorator
