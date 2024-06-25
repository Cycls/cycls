from cycls import Cycls

graph = "https://7c0ed7ef-03ed-48bd-8eda-a6a9a5e846e2-00-2bs5oneddesjb.picard.replit.dev"
cycls = Cycls(graph=graph)

# cycls = Cycls()

@cycls("@bake")
def bake_app(x):
    print("history", x.history)
    print("session id", x.id)
    return x.content + " bake"

@cycls("@take")
async def take_app(x):
    print("history", x.history)
    print("session id", x.id)
    return x.content + " take"

@cycls("@op")
async def agent_app(x):
    return cycls.call("@groq", x.content) # why not await?
    
# looking for parity with OpenAI/Groq streams!...
cycls.push()

