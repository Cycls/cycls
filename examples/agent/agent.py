import cycls

# Set ANTHROPIC_API_KEY or OPENAI_API_KEY env var before running

@cycls.agent(model="anthropic/claude-sonnet-4-20250514")
def coder():
    pass

coder.local()
