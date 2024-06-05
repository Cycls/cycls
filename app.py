from cycls import Cycls, Text, Message

push = Cycls(debug=True)

@push("cake")
async def app(x:Message):
  return Text(x.content)