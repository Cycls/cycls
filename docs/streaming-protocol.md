# Cycls Streaming Protocol

Documentation for backend and front-end teams on the `/chat/cycls` streaming protocol.

---

## Backend Example

```python
import cycls

@cycls.app(pip=["openai"], theme="dev")
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
            yield {"type": "thinking", "thinking": event.delta}
        elif event.type == "response.output_text.delta":
            yield event.delta

chat.local()  # or chat.deploy()
```

### Context Object

- `context.messages` - List of `{"role": "...", "content": "..."}` (text-only)
- `context.messages.raw` - Full raw message objects from front-end (includes `parts`)

### Yielding Content

| Yield | Result |
|-------|--------|
| `"plain string"` | Text component (supports markdown) |
| `{"type": "thinking", "thinking": "..."}` | Thinking bubble |
| `{"type": "code", "code": "...", "language": "python"}` | Code block |
| `{"type": "table", "headers": [...]}` then `{"type": "table", "row": [...]}` | Streaming table |
| `{"type": "callout", "callout": "...", "style": "info", "title": "..."}` | Callout box |
| `{"type": "image", "src": "...", "alt": "...", "caption": "..."}` | Image |

---

## Streaming Protocol (`/chat/cycls`)

The backend sends each yielded item as an SSE event. Plain strings are converted to `{"type": "text", "text": "..."}`.

### Wire Format

```
data: {"type": "thinking", "thinking": "Let me "}
data: {"type": "thinking", "thinking": "analyze..."}
data: {"type": "text", "text": "Here is "}
data: {"type": "text", "text": "the answer."}
data: {"type": "callout", "callout": "Done!", "style": "success"}
data: [DONE]
```

### Backend Encoder

```python
def sse(item):
    if not item: return None
    if not isinstance(item, dict): item = {"type": "text", "text": item}
    return f"data: {json.dumps(item)}\n\n"

async def encoder(stream):
    async for item in stream:
        if msg := sse(item): yield msg
    yield "data: [DONE]\n\n"
```

---

## Front-End Decoder

### Message Structure

```javascript
// User message
{ role: 'user', content: 'Hello' }

// Assistant message
{ role: 'assistant', parts: [
    { type: 'thinking', thinking: '...' },
    { type: 'text', text: '...' },
    { type: 'code', code: '...', language: 'python' }
]}
```

### Decoder Implementation

```javascript
let currentPart = null;

function handleItem(item) {
  const type = item.type;

  // Same type as current? Append content
  if (currentPart && currentPart.type === type) {
    if (item.row) currentPart.rows.push(item.row);
    else if (item[type]) currentPart[type] = (currentPart[type] || '') + item[type];
  } else {
    // New component
    currentPart = { ...item };
    if (item.headers) currentPart.rows = [];
    assistantMsg.parts.push(currentPart);
  }
}
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
        const item = JSON.parse(data);
        const type = item.type;

        if (currentPart && currentPart.type === type) {
          if (item.row) currentPart.rows.push(item.row);
          else if (item[type]) currentPart[type] = (currentPart[type] || '') + item[type];
        } else {
          currentPart = { ...item };
          if (item.headers) currentPart.rows = [];
          assistantMsg.parts.push(currentPart);
        }
        render();
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
  text: (props) => marked.parse(props.text || ''),

  thinking: (props) => `
    <div class="thinking-bubble">
      <div class="label">Thinking</div>
      <div>${props.thinking}</div>
    </div>
  `,

  code: (props) => `
    <pre><code class="language-${props.language || ''}">${props.code}</code></pre>
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
    <div class="callout callout-${props.style || 'info'}">
      ${props.title ? `<strong>${props.title}</strong>` : ''}
      <div>${props.callout}</div>
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
    components[part.type]?.(part) || ''
  ).join('');
}
```

---

## Summary

| Layer | Responsibility |
|-------|----------------|
| **Backend** | Yield strings or `{type, <type>: value, ...}` dicts |
| **Encoder** | Convert to SSE `data: {...}` messages |
| **Decoder** | Parse SSE, track current type, build `parts` array |
| **Renderer** | Convert `parts` to HTML components |
