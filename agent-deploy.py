import cycls

agent = cycls.Agent(api_key="...")

@agent()
async def func(context):
    yield "hi"

agent.deploy(prod=True)