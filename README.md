</br></br>
<p align="center">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://cycls.com/static/assets/logo-gold.svg">
      <source media="(prefers-color-scheme: light)" srcset="https://cycls.com/static/assets/logo.svg">
      <img alt="Cycls" src="https://cycls.com/static/assets/logo.svg" width="150">
    </picture>
</p>
</br></br>

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

# Apps ✦
Instantly publish and share AI apps

```py
from cycls import Cycls

cycls = Cycls()

@cycls("@spark") # pick a unique handle name
def app(x):
    return x.content + "from spark"

cycls.push()
```
`cycls.push()` will then publish the app `@spark-dev` on [cycls.com/@spark-dev](https://cycls.com/@spark-dev) in development mode. Make sure to pick a unique app name; Cycls maintains a global namespace for handles.
## Async Apps
For performance, make the function asynchronous. The following is an async app with message `history` and session `id`
```py
from cycls import Cycls

cycls = Cycls()

@cycls("@spark")
async def app(x):
    print(x.history, x.id)
    return x.content + "from spark"

cycls.push()
```

# Agents ✧
Call any public app as an agent, see [explore](https://explore.cycls.com)
```py
from cycls import Cycls

cycls = Cycls()

@cycls("@spark")
async def app(x):
    return cycls.call("@groq",
                       x.content)

cycls.push()
```

### Try it live
- [cycls.com/@groq](https://cycls.com/@groq)       | [groq.py](https://github.com/Cycls/examples/blob/main/groq.py)
- [cycls.com/@openai](https://cycls.com/@openai)   | [openai.py](https://github.com/Cycls/examples/blob/main/openai.py)
- [cycls.com/@groq](https://cycls.com/@anthropic)  | [groq.py](https://github.com/Cycls/examples/blob/main/anthropic.py)
- [cycls.com/@openai](https://cycls.com/@gemini)   | [openai.py](https://github.com/Cycls/examples/blob/main/gemini.py)
