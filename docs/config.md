# /config Endpoint

Frontend configuration endpoint that returns agent settings and auth configuration.

## Request

```
GET /config
```

## Response

```json
{
  "header": "Welcome to MyAgent",
  "intro": "How can I help you today?",
  "title": "MyAgent",
  "prod": true,
  "auth": true,
  "tier": "free",
  "analytics": false,
  "org": "acme-corp",
  "pk": "pk_live_..."
}
```

## Fields

| Field | Type | Description |
|-------|------|-------------|
| `header` | string | Display header text |
| `intro` | string | Introduction/welcome message |
| `title` | string | Page title |
| `prod` | boolean | Production mode flag |
| `auth` | boolean | Whether authentication is required |
| `tier` | string | Subscription tier (`"free"`, `"cycls_pass"`, etc.) |
| `analytics` | boolean | Whether analytics is enabled |
| `org` | string? | Organization identifier (nullable) |
| `pk` | string | Clerk publishable key for authentication |

## Usage

Fetch config on app initialization to configure auth and UI:

```javascript
const res = await fetch('/config');
const config = await res.json();

if (config.auth) {
  // Initialize Clerk with config.pk
}

document.title = config.title;
```
