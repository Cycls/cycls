# Cycls Streaming Protocol

Documentation for backend and front-end teams on the `/chat/cycls` streaming protocol.

---

## Backend Example

```python
import cycls

agent = cycls.Agent(pip=["openai"], theme="dev")

@agent('openai-chat')
async def chat(context):
    from openai import AsyncOpenAI
    client = AsyncOpenAI()

    stream = await client.responses.create(
        model="o3-mini",
        input=context.messages,
        stream=True,
        reasoning={"effort": "medium", "summary": "auto"},
    )

    async for event in stream:
        if event.type == "response.reasoning_summary_text.delta":
            yield {"name": "thinking", "content": event.delta}
        elif event.type == "response.output_text.delta":
            yield event.delta

agent.deploy(prod=False)
```

### Context Object

- `context.messages` - List of `{"role": "...", "content": "..."}` (text-only)
- `context.messages.raw` - Full raw message objects from front-end (includes `parts`)

### Yielding Content

| Yield | Result |
|-------|--------|
| `"plain string"` | Text component (supports markdown) |
| `{"name": "thinking", "content": "..."}` | Thinking bubble |
| `{"name": "code", "content": "...", "language": "python"}` | Code block |
| `{"name": "table", "headers": [...]}` then `{"name": "table", "row": [...]}` | Streaming table |
| `{"name": "callout", "content": "...", "type": "info", "_complete": True}` | Complete callout |
| `{"name": "image", "src": "...", "_complete": True}` | Complete image |

**Note:** Use `_complete: True` for non-streaming components (sent all at once).

---

## Streaming Protocol (`/chat/cycls`)

The backend encodes yielded items into SSE (Server-Sent Events) with a compact protocol.

### Protocol Messages

| Code | Name | Purpose | Payload |
|------|------|---------|---------|
| `+` | Start | Begin new component | `["+", name, props]` |
| `~` | Delta | Stream content to current component | `["~", props]` |
| `-` | Close | End current component | `["-"]` |
| `=` | Complete | Send complete component (non-streaming) | `["=", {name, ...props}]` |

### Backend Encoder Logic

```python
class Encoder:
    def __init__(self):
        self.cur = None  # current component name

    def process(self, item):
        # Plain strings become text components
        if not isinstance(item, dict):
            item = {"name": "text", "content": item}

        name = item.get("name")
        done = item.get("_complete")
        props = {k: v for k, v in item.items() if k not in ("name", "_complete")}

        if done:
            # Complete component - close current, send as "="
            self.close()
            yield ["=", {"name": name, **props}]
        elif name != self.cur:
            # New component - close previous, start new with "+"
            self.close()
            self.cur = name
            yield ["+", name, props]
        else:
            # Same component - stream delta with "~"
            yield ["~", props]
```

### Example Stream

Backend yields:
```python
yield {"name": "thinking", "content": "Let me "}
yield {"name": "thinking", "content": "think..."}
yield "Here is "
yield "the answer."
yield {"name": "callout", "content": "Done!", "type": "success", "_complete": True}
```

Wire format (SSE):
```
data: ["+", "thinking", {"content": "Let me "}]

data: ["~", {"content": "think..."}]

data: ["-"]

data: ["+", "text", {"content": "Here is "}]

data: ["~", {"content": "the answer."}]

data: ["-"]

data: ["=", {"name": "callout", "content": "Done!", "type": "success"}]

data: [DONE]
```

---

## Front-End Decoder

### Message Structure

```javascript
// User message
{ role: 'user', content: 'Hello' }

// Assistant message
{ role: 'assistant', parts: [
    { name: 'thinking', content: '...' },
    { name: 'text', content: '...' },
    { name: 'code', content: '...', language: 'python' }
]}
```

### Decoder Implementation

```javascript
const decode = {
  // "+" Start new component
  '+': ([, name, props]) => {
    currentPart = { name, ...props };
    if (props.headers) currentPart.rows = [];  // table support
    assistantMsg.parts.push(currentPart);
  },

  // "~" Delta - append to current component
  '~': ([, props]) => {
    if (!currentPart) return;
    for (const [k, v] of Object.entries(props)) {
      if (k === 'content')
        currentPart.content = (currentPart.content || '') + v;
      else if (k === 'row')
        currentPart.rows.push(v);
      else
        currentPart[k] = v;
    }
  },

  // "-" Close current component
  '-': () => {
    currentPart = null;
  },

  // "=" Complete component (non-streaming)
  '=': ([, props]) => {
    assistantMsg.parts.push(props);
  }
};
```

### Full Streaming Example

```javascript
async function streamResponse(userMessage) {
  messages.push({ role: 'user', content: userMessage });
  messages.push({ role: 'assistant', parts: [] });

  const response = await fetch('/chat/cycls', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      messages: messages.slice(0, -1).map(m => ({
        role: m.role,
        content: m.content,
        parts: m.parts
      }))
    })
  });

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let assistantMsg = messages[messages.length - 1];
  let currentPart = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      const data = line.slice(6);
      if (data === '[DONE]') continue;

      try {
        const msg = JSON.parse(data);
        decode[msg[0]]?.(msg);
        render();  // re-render UI
      } catch (e) {
        console.error('Parse error:', e);
      }
    }
  }
}
```

---

## Component Renderers

```javascript
const components = {
  text: (props) => marked.parse(props.content || ''),

  thinking: (props) => `
    <div class="thinking-bubble">
      <div class="label">Thinking</div>
      <div>${props.content}</div>
    </div>
  `,

  code: (props) => `
    <pre><code class="language-${props.language || ''}">${props.content}</code></pre>
  `,

  table: (props) => `
    <table>
      <thead>
        <tr>${props.headers?.map(h => `<th>${h}</th>`).join('')}</tr>
      </thead>
      <tbody>
        ${props.rows?.map(row => `
          <tr>${row.map(cell => `<td>${cell}</td>`).join('')}</tr>
        `).join('')}
      </tbody>
    </table>
  `,

  callout: (props) => `
    <div class="callout callout-${props.type || 'info'}">
      ${props.title ? `<strong>${props.title}</strong>` : ''}
      <div>${props.content}</div>
    </div>
  `,

  image: (props) => `
    <img src="${props.src}" alt="${props.alt || ''}" />
    ${props.caption ? `<p>${props.caption}</p>` : ''}
  `
};

// Render assistant message
function renderAssistant(msg) {
  return msg.parts.map(part =>
    components[part.name]?.(part) || ''
  ).join('');
}
```

---

## Summary

| Layer | Responsibility |
|-------|----------------|
| **Backend** | Yield strings or `{name, content, ...}` dicts |
| **Encoder** | Convert to `+`/`~`/`-`/`=` SSE messages |
| **Decoder** | Parse SSE, build `parts` array |
| **Renderer** | Convert `parts` to HTML components |
