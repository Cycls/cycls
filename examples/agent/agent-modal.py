import cycls

@cycls.agent(modal_keys=["YOUR_MODAL_AK", "YOUR_MODAL_AS"])
async def chat(context):
    """A simple streaming agent."""
    yield "Hello! "
    yield "How can I help you today?"

chat.modal(prod=False)
