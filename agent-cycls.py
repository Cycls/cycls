import cycls
from utils import u

agent = cycls.Agent(copy=["utils.py"], api_key="...")

@agent("cake")
async def func(context):
    print(u(context))
    yield "hi"

agent.cycls(prod=False)