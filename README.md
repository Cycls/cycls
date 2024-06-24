</br></br><p align="center"><img src="https://cycls.com/static/assets/favicon.svg" alt="Cycls"></p></br>

<div align="center">
    <a href="https://pypi.org/project/cycls/" target="_blank" rel="noopener noreferrer">
        <img loading="lazy" src="https://img.shields.io/pypi/v/cycls.svg" alt="PyPI" class="img_ev3q" style="display: inline;">
    </a>
    <a href="https://discord.gg/BMnaMatDC7" target="_blank" rel="noopener noreferrer">
        <img loading="lazy" src="https://img.shields.io/discord/1175782747164389466" alt="Discord" class="img_ev3q" style="display: inline;">
    </a>
</div>

</br>

```sh
pip install cycls
```

```py
from cycls import Cycls

cycls = Cycls()

# sync app on https://cycls.com/@spark
@cycls("spark")
def spark_app(message):
    print("history", message.history)
    print("session id", message.id)
    return message.content + "from spark"

# async app on https://cycls.com/@cake
@cycls("cake")
async def cake_app(message):
    print("history", message.history)
    print("session id", message.id)
    return message.content + "from cake"

# publish to https://cycls.com
cycls.push()
```

Return a string. Supports markdown. Supports generators for streaming responses.

try it live
- https://cycls.com/@groq
- https://cycls.com/@openai

code examples
- https://github.com/Cycls/examples/blob/main/groq.py
- https://github.com/Cycls/examples/blob/main/openai.py
