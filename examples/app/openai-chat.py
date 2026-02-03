import cycls

def to_responses_format(messages):
    """Convert Chat Completions format to Responses API format."""
    result = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            new_content = []
            for part in content:
                if part.get("type") == "image_url":
                    new_content.append({
                        "type": "input_image",
                        "image_url": part["image_url"]["url"]
                    })
                elif part.get("type") == "text":
                    new_content.append({"type": "input_text", "text": part["text"]})
                else:
                    new_content.append(part)
            result.append({"role": msg["role"], "content": new_content})
        else:
            result.append(msg)
    return result

@cycls.app(pip=["openai"], copy=[".env"])
async def openai_chat(context):
    from openai import AsyncOpenAI
    client = AsyncOpenAI()

    stream = await client.responses.create(
        model="o3-mini",
        input=to_responses_format(context.messages),
        stream=True,
        reasoning={"effort": "medium", "summary": "auto"},
    )

    async for event in stream:
        if event.type == "response.reasoning_summary_text.delta":
            yield {"type": "thinking", "thinking": event.delta}
        elif event.type == "response.output_text.delta":
            yield event.delta

openai_chat.local()
