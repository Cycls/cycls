import cycls

cycls.api_key = "YOUR_CYCLS_API_KEY"

@cycls.app()
async def hello(context): # or def hello(context):
    """A simple streaming agent."""
    yield "Hello! "
    yield "How can I help you today?"

hello.local() # hello.deploy() or hello._local() for non-Docker
