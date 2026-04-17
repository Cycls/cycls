"""cycls.Web — fluent immutable builder for chat UI / web surface config.

Holds auth, title, theme, billing plan, analytics, and public static files.
Passed to `@cycls.agent(web=...)` as a single composed object, or equivalent
fields can be passed directly on `@cycls.agent` for the simple case —
`web=` and direct chat kwargs are mutually exclusive.
"""
from typing import List, Optional

from .auth import JWT


THEMES = ["default", "dev"]


class Web:
    def __init__(self):
        self._auth: Optional[JWT] = None
        self._title: Optional[str] = None
        self._theme: str = "default"
        self._cycls_pass: bool = False
        self._analytics: bool = False
        self._copy_public: List[str] = []

    def _copy(self, **updates):
        new = Web.__new__(Web)
        new.__dict__ = {**self.__dict__, **updates}
        return new

    def auth(self, provider: Optional[JWT]):
        if provider is not None and not isinstance(provider, JWT):
            raise TypeError(
                f"auth must be a cycls.JWT instance or None; got {type(provider).__name__}"
            )
        return self._copy(_auth=provider)

    def title(self, text: str):
        return self._copy(_title=text)

    def theme(self, name: str):
        if name not in THEMES:
            raise ValueError(f"Unknown theme: {name}. Available: {THEMES}")
        return self._copy(_theme=name)

    def cycls_pass(self, on: bool = True):
        """Register this agent as part of the Cycls Pass subscription.
        Triggers a CMS fetch at serve time to populate wallet-pass metadata."""
        return self._copy(_cycls_pass=on)

    def analytics(self, on: bool = True):
        return self._copy(_analytics=on)

    def copy_public(self, *files: str):
        return self._copy(_copy_public=list(files))
