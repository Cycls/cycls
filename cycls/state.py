from agentfs_sdk import AgentFS, AgentFSOptions


async def create_state(user_id: str = "default"):
    """Create state instance scoped to end-user."""
    return await AgentFS.open(AgentFSOptions(id=user_id))
