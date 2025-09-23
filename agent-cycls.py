import cycls

agent = cycls.Agent(api_key="...")

@agent("cake")
async def func(context):
    yield "hi"

agent.cycls(prod=False)