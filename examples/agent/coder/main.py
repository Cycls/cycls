import cycls

@cycls.agent(model="anthropic/claude-sonnet-4")
def coder():
    pass

coder.local()
