import cycls

@cycls.agent()
# async def hello(context):
def hello(context):
    """A simple streaming agent."""
    yield "Hello! "
    yield "How can I help you today?"

hello.local()  # or hello._local() for non-Docker
