import cycls
from cycls import UI
import asyncio

agent = cycls.Agent(theme="dev")

@agent('native-demo')
async def func(context):
    yield "# Native Components Demo\n\n"

    # Streaming thinking bubble - each yield adds to the same bubble
    yield UI.thinking("Let me ")
    await asyncio.sleep(0.3)
    yield UI.thinking("think about ")
    await asyncio.sleep(0.3)
    yield UI.thinking("this problem...")
    await asyncio.sleep(0.5)
    yield UI.thinking(" Analyzing the request and formulating a response.")

    # Plain text closes the thinking bubble automatically
    yield "\n\nHere's some data:\n\n"

    # Streaming table - rows appear one by one!
    yield UI.table(headers=["Feature", "Status", "Type"])
    await asyncio.sleep(0.3)
    yield UI.table(row=["Text Streaming", "✓", "Built-in"])
    await asyncio.sleep(0.3)
    yield UI.table(row=["Thinking Bubble", "✓", "Streaming"])
    await asyncio.sleep(0.3)
    yield UI.table(row=["Tables", "✓", "Streaming!"])
    await asyncio.sleep(0.3)
    yield UI.table(row=["Callouts", "✓", "Complete"])

    yield "\n\n"

    yield UI.callout(
        callout="Native components work alongside HTML passthrough!",
        style="success",
        title="It works!"
    )

    yield "\n\n"

    # HTML passthrough still works
    yield '<div class="bg-gradient-to-r from-blue-500 to-purple-500 text-white p-4 rounded-lg">'
    yield '<strong>HTML passthrough</strong> still works too!'
    yield '</div>'

    yield "\n\nDone!"

agent.local(port=8080)
