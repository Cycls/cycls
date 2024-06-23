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
from cycls import Cycls, Text

cycls = Cycls()

# sync app on https://cycls.com/@spark
@cycls("spark")
def spark_app(x):
    print("history", x.history)
    print("session id", x.id)
    return Text(x.content+" from spark")

# async app on https://cycls.com/@cake
@cycls("cake")
async def cake_app(x):
    print("history", x.history)
    print("session id", x.id)
    return Text(x.content+" from cake")

# publish to https://cycls.com
cycls.push()
```

- `Text` renders markdown
- `Text` is both streaming/bulk based on input

try it live
- https://cycls.com/@groq
- https://cycls.com/@openai

code examples
- https://github.com/Cycls/examples/blob/main/groq.py
- https://github.com/Cycls/examples/blob/main/openai.py
