# from cycls import Cycls, Text, Message

# push = Cycls()

# @push("cake")
# async def app(x:Message):
#   return Text(x.content)

from cycls import Cycls, Text, Message

push = Cycls()

@push("cake")
def app(x:Message):
  return Text(x.content)