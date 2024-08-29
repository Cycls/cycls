from cycls import Cycls

# net = "https://7c0ed7ef-03ed-48bd-8eda-a6a9a5e846e2-00-2bs5oneddesjb.picard.replit.dev"

# cycls = Cycls(net=net)

cycls = Cycls()

@cycls("@hack")
async def take_app(x):
    print("history", x.history)
    print("session id", x.id)
    return x.content + " take"

# @cycls("@cake")
# async def cake_app(x):
#     print("history", x.history)
#     print("session id", x.id)
#     return x.content + " cake"

# @cycls("@agent")
# async def agent_app(x):
#     return cycls.call("@groq", x.content) # why not await?
    
# looking for parity with OpenAI/Groq streams!...
cycls.push()