import cycls
from utils import u

agent = cycls.Agent(pip=["openai"], copy=["utils.py"], api_key="...")

@agent("cake")
async def func(context):
    print(u(context))
    yield "cake"

agent.deploy(prod=False)