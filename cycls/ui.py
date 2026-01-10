thinking = lambda thinking: {"type": "thinking", "thinking": thinking}
status = lambda status: {"type": "status", "status": status}
code = lambda code, language=None: {"type": "code", "code": code, "language": language}
table = lambda headers=None, row=None: {"type": "table", "headers": headers} if headers else {"type": "table", "row": row} if row else None
callout = lambda callout, style="info", title=None: {"type": "callout", "callout": callout, "style": style, "title": title}
image = lambda src, alt=None, caption=None: {"type": "image", "src": src, "alt": alt, "caption": caption}