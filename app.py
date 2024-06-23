from cycls import Cycls, Text

network = "https://7c0ed7ef-03ed-48bd-8eda-a6a9a5e846e2-00-2bs5oneddesjb.picard.replit.dev"
cycls = Cycls(network=network)

@cycls("spark")
def spark_app(x):
    print("history",x.history)
    print("session id",x.id)
    return Text(x.content+" spark")

@cycls("cake")
async def cake_app(x):
    print("history",x.history)
    print("session id",x.id)
    return Text(x.content+" cake")

cycls.push()