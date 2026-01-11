import cycls

agent = cycls.Agent()

@agent("hello")
async def hello(context):
    """A simple streaming agent."""
    yield "Hello! "
    yield "How can I help you today?"

agent.local() # agent._local()