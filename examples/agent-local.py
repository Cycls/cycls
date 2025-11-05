import cycls

agent = cycls.Agent()

@agent()
async def func(context):
    yield "hi"

agent.local()