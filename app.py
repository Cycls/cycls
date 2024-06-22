# from groq import AsyncGroq

# groq = AsyncGroq(api_key="YOUR_KEY")

# async def llm(messages):
#     stream = await groq.chat.completions.create(
#         messages=messages,
#         model="llama3-70b-8192",
#         temperature=0.5, max_tokens=1024, top_p=1, stop=None, 
#         stream=True,
#     )

#     async def event_stream():
#         async for chunk in stream:
#             yield f"{chunk.choices[0].delta.content}"

#     return event_stream()

# @push("groq-app")
# async def app(m:Message):
#     x  = [{"role": "system", "content": "you are a helpful assistant."}]
#     x +=  m.history
#     x += [{"role": "user", "content": m.content}]
#     stream = await llm(x)
#     return Text(stream)

from cycls import Cycls
from cycls import Message, Text
network = "https://7c0ed7ef-03ed-48bd-8eda-a6a9a5e846e2-00-2bs5oneddesjb.picard.replit.dev"
push = Cycls(network=network)
@push("spark")
def app(m: Message):
    # print(x)
    print("history",m.history)
    print("session_id",m.session_id)
    return Text(m.content)