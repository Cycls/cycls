</br></br><p align="center"><img src="https://cycls.com/static/assets/logo-gold.svg" alt="Cycls" width="150"></p></br>

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

# Apps
Instantly publish and share AI `agents` / `apps`

```py
from cycls import Cycls

cycls = Cycls()

@cycls("@spark")
def app(x):
    return x.content + "from spark"

cycls.push()
```
`cycls.push()` will then publish the app `@spark` on https://cycls.com/@spark
## Async Apps
For performance and scale, make the app function asynchronous. The following is an async app with message `history` and session `id`
```py
from cycls import Cycls

cycls = Cycls()

@cycls("@spark")
async def app(x):
    print(x.history)
    print(x.id)
    return x.content + "from spark"

cycls.push()
```

# Agents
Apps in Cycls double as `agents`. Call agents from the Cycls [universe](https://explore.cycls.com).
```py
from cycls import Cycls

cycls = Cycls()

@cycls("@spark")
async def app(x):
    # agent call @groq
    return cycls.call("@groq", x.content)

cycls.push()
```

### Try it live
- https://cycls.com/@groq   | [groq.py](https://github.com/Cycls/examples/blob/main/groq.py)
- https://cycls.com/@openai | [openai.py](https://github.com/Cycls/examples/blob/main/openai.py)

</br>✦/✧</br>
   
