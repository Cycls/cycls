import cycls

agent = cycls.Agent(
    pip=["openai"],
    key="YOUR_CYCLS_API_KEY"
)

@agent("assistant", auth=True)
async def assistant(context):
    """Deploy an agent to Cycls cloud."""
    yield f"You said: {context.messages[-1]['content']}"

agent.deploy()
