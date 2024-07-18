</br>
<p align="center">
  <img width="200" src="https://cycls.com/static/assets/logo-gold.svg" alt="cycls logo">
</p>

<h1 align="center">
  Apps with Agency
</h1>

<h3 align="center">
  The network for native AI apps and AI agents
</h3>

<h4 align="center">
  <a href="https://docs.cycls.com">Docs</a> |
  <a href="https://cycls.com">Website</a> |
  <a href="https://discord.gg/XbxcTFBf7J">Discord</a> |
  <a href="https://x.com/cycls_">Twitter</a>
</h4>

<h4 align="center">
  <a href="https://pypi.org/project/cycls/">
    <img alt="Last 1 month downloads for the Python SDK" loading="lazy" width="200" height="20" decoding="async" data-nimg="1"
    style="color:transparent;width:auto;height:100%" src="https://img.shields.io/pypi/dm/cycls?label=PyPI%20Downloads">
  </a>
</h4>

## What is Cycls?
Cycls is a network for AI-native apps, where apps can work together. Our SDK turns your apps into nodes in the network, acting as both server and client. This enables seamless integration between AI apps while serving users. Your apps are streamed directly from your infrastructure, giving you full control over your data and deployment.

Cycls is designed to break down the barriers between isolated apps and maximize their collective potential. [Learn more about Cycls streaming architecture](https://docs.cycls.com/home/overview).

with **app streaming** you can:
- Turn existing code into instant web apps
- Allow apps to call and utilize each other
- Generate UIs on-the-fly with LLMs
- Integrate with any model, framework, or infrastructure

---
## Getting started
1. Install SDK
```sh
pip install cycls
```
2. Start Streaming
   
In this example, the `@spark` app simply echoes the user's input by accessing `message.content` string and returning it back:
```python
from cycls import Cycls

cycls = Cycls()

@cycls("@spark")
def app(message):
    return message.content

cycls.push()
```

3. Connect to LLM
   
To connect `@spark` app to an LLM, simply wrap the `message.content` with your LLM function and return the result. Here's an example:
```python
...
@cycls("@spark")
def app(message):
    return llm(message.content)
...
```

> Visit our [documentation](https://docs.cycls.com/home/getting-started) to learn more about Cycls and how to get started.

---

Check out our [Explore page](https://explore.cycls.com/) to see Cycls apps in action and visit our [Cookbook](https://github.com/Cycls/examples) for practical examples and use cases.




