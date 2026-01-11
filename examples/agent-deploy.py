import cycls

cycls.api_key = "YOUR_CYCLS_API_KEY"

@cycls.agent(pip=["openai"], auth=True)
async def assistant(context):
    """Deploy an agent to Cycls cloud."""
    yield f"You said: {context.messages[-1]['content']}"

assistant.deploy()