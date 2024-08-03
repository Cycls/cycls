<p align="center">
  <img src="https://github.com/user-attachments/assets/96bd304d-8116-4bce-8b8f-b08980875ad7" width="800px" alt="Cycls Banner">
</p>

<h3 align="center">
Generate live apps from code in minutes with built-in memory, <br/>rich hypermedia content, and cross-platform support
</h3>

<h4 align="center">
  <a href="https://cycls.com">Website</a> |
  <a href="https://docs.cycls.com">Docs</a> |
  <a href="https://docs.cycls.com">Blog</a>
</h4>

<h4 align="center">
  <a href="https://pypi.python.org/pypi/cycls"><img src="https://img.shields.io/pypi/v/cycls.svg?label=cycls+pypi&color=blueviolet" alt="cycls Python package on PyPi" /></a>
  <a href="https://blog.cycls.com"><img src="https://img.shields.io/badge/newsletter-blueviolet.svg?logo=substack&label=cycls" alt="Cycls newsletter" /></a>
  <a href="https://x.com/cycls_">
    <img src="https://img.shields.io/twitter/follow/cycls_" alt="Cycls Twitter" />
  </a>
</h4>


## Cycls: The AI App Generator
Cycls[^1] streamlines AI application development by generating apps from high-level descriptions. It eliminates boilerplate, ensures cross-platform compatibility, and manages memory - all from a single codebase.

With Cycls, you can quickly prototype ideas and then turn them into production apps, while focusing on AI logic and user interactions rather than wrestling with implementation details.

## ✨ Core Features
- **Fast App Generation**: Create live web apps from code in minutes
- **Built-in Memory Management**: Integrated state and session management
- **Rich Hypermedia Content**: Support for various media types (text, images, audio, video, interactive elements)
- **Framework Agnostic**: Compatible with a wide range of AI frameworks and models

## 🚀 Quickstart
### Installation
```
pip install cycls
```

### Basic usage
```py
from cycls import Cycls

cycls = Cycls()

@cycls("@my-app")
def app():
    return "Hello World!"

cycls.push()
```
This creates an app named "@my-app" that responds with "Hello World!".

The `@cycls("@my-app")` decorator registers your app, and `cycls.push()` streams it to Cycls platform.

To see a live example, visit https://cycls.com/@spark.

> [!IMPORTANT]
> Use a unique name for your app (like "@my-app"). This is your app's identifier on Cycls.

> [!NOTE]
> Your apps run on your infrastructure and are streamed in real-time to Cycls.

## 📖 Documentation
For more detailes and instructions, visit our documentation at [docs.cycls.com](https://docs.cycls.com/).

## 🗺️ Roadmap
- **iOS and Android apps**
- **User management**
- **JavaScript SDK**
- **Public API**
- **Cross-app communication**

## 🙌 Support 
Join our Discord community for support and discussions. You can reach us on:

- [Join our Discord](https://discord.gg/XbxcTFBf7J)
- [Join our newsletter](https://blog.cycls.com)
- [Follow us on Twitter](https://x.com/cycls_)
- [Email us](mailto:hi@cycls.com)

[^1]: The name "Cycls" is a play on "cycles," referring to the continuous exchange between AI prompts (generators) and their responses (generated).
