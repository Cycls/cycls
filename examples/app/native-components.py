import cycls
import asyncio

@cycls.app()
async def native_demo(context):
    yield "# Native Components Demo\n\n"

    # Streaming thinking bubble - each yield adds to the same bubble
    yield {"type": "thinking", "thinking": "Let me "}
    await asyncio.sleep(0.3)
    yield {"type": "thinking", "thinking": "think about "}
    await asyncio.sleep(0.3)
    yield {"type": "thinking", "thinking": "this problem..."}
    await asyncio.sleep(0.5)
    yield {"type": "thinking", "thinking": " Analyzing the request and formulating a response."}

    # Plain text closes the thinking bubble automatically
    yield "Here's some data:"

    # Streaming table - rows appear one by one!
    yield {"type": "table", "headers": ["Feature", "Status", "Type"]}
    await asyncio.sleep(0.3)
    yield {"type": "table", "row": ["Text Streaming", "✓", "Built-in"]}
    await asyncio.sleep(0.3)
    yield {"type": "table", "row": ["Thinking Bubble", "✓", "Streaming"]}
    await asyncio.sleep(0.3)
    yield {"type": "table", "row": ["Tables", "✓", "Streaming!"]}
    await asyncio.sleep(0.3)
    yield {"type": "table", "row": ["Callouts", "✓", "Complete"]}

    await asyncio.sleep(0.6)
    yield {"type": "callout", "callout": "Native components work alongside HTML passthrough!", "style": "success", "title": "It works!"}

    # HTML passthrough still works
    await asyncio.sleep(0.6)
    yield '<div class="bg-gradient-to-r from-blue-500 to-purple-500 text-white p-4 rounded-lg">'
    yield '<strong>HTML passthrough</strong> still works too!'
    yield '</div>'

    yield "Done!"

native_demo.local(port=8080)