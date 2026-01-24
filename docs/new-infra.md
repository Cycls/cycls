# New Infrastructure

Use `_deploy` for the new deployment infrastructure.

## Get Your API Key

Get your API key from: https://accounts.cycls.com/user/api-keys

## Configuration

```python
import cycls

cycls.api_key = "YOUR_API_KEY"
cycls.base_url = "https://api-572247013948.me-central1.run.app"
```

Or via environment variables:

```bash
export CYCLS_API_KEY=your_key_here
export CYCLS_BASE_URL=https://api-572247013948.me-central1.run.app
```

## Deploy

```python
import cycls

cycls.api_key = "YOUR_API_KEY"
cycls.base_url = "https://api-572247013948.me-central1.run.app"

@cycls.app(pip=["openai"])
async def my_app(context):
    yield "Hello!"

my_app._deploy()
```
