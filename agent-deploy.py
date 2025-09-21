from cycls import function

@function(pip_install=["cycls"],
          api_key="")
def cycls_agent(port):
    import cycls
    agent = cycls.Agent()
    @agent()
    async def hello(context):
        yield "hi"

    agent.run(port=port)

cycls_agent.deploy(port=8080)
# cycls_agent.run(port=8080)