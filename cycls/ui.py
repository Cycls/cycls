thinking = lambda content: {"name": "thinking", "content": content}
status = lambda content: {"name": "status", "content": content}
code = lambda content, language=None: {"name": "code", "content": content, "language": language}
table = lambda headers=None, row=None: {"name": "table", "headers": headers} if headers else {"name": "table", "row": row} if row else None
callout = lambda content, type="info", title=None: {"name": "callout", "content": content, "type": type, "title": title, "_complete": True}
image = lambda src, alt=None, caption=None: {"name": "image", "src": src, "alt": alt, "caption": caption, "_complete": True}
