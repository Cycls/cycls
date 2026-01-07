class UI:
    """Native UI components for streaming agents"""

    @staticmethod
    def thinking(content):
        """Streaming thinking bubble"""
        return {"name": "thinking", "content": content}

    @staticmethod
    def status(content):
        """Streaming status indicator"""
        return {"name": "status", "content": content}

    @staticmethod
    def code(content, language=None):
        """Streaming code block"""
        return {"name": "code", "content": content, "language": language}

    @staticmethod
    def table(headers=None, row=None):
        """Streaming table - start with headers, then stream rows"""
        if headers:
            return {"name": "table", "headers": headers}
        if row:
            return {"name": "table", "row": row}

    @staticmethod
    def callout(content, type="info", title=None):
        """Complete callout/alert box"""
        return {"name": "callout", "content": content, "type": type, "title": title, "_complete": True}

    @staticmethod
    def image(src, alt=None, caption=None):
        """Complete image"""
        return {"name": "image", "src": src, "alt": alt, "caption": caption, "_complete": True}
