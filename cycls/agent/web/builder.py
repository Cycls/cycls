"""cycls.Web — fluent immutable builder for chat UI / web surface config.

Holds auth, title, theme, billing plan, analytics, and public static files.
Passed to `@cycls.agent(web=...)` as a single composed object, or equivalent
fields can be passed directly on `@cycls.agent` for the simple case —
`web=` and direct chat kwargs are mutually exclusive.
"""
from typing import List, Optional

from cycls.app.auth import JWT


THEMES = ["default", "dev"]


class Web:
    def __init__(self):
        self._auth: Optional[JWT] = None
        self._title: Optional[str] = None
        self._theme: str = "default"
        self._cms: Optional[str] = None
        self._analytics: bool = False
        self._suggestions: bool = False
        self._affiliate: Optional[str] = None
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

    def cms(self, host: str = "cycls.ai"):
        """Register this agent with a CMS. At serve time, the framework fetches
        metadata from the named CMS (default `cms.cycls.ai/agents/{name}`) to
        populate wallet-pass UI and other client-rendered product surfaces."""
        return self._copy(_cms=host)

    def analytics(self, on: bool = True):
        return self._copy(_analytics=on)

    def suggestions(self, on: bool = True):
        """Show the prompt-starter suggestions on the empty-chat screen. Off by default."""
        return self._copy(_suggestions=on)

    def affiliate(self, api_key: str):
        """Enable affiliate/referral tracking with this provider API key (e.g.
        a Rewardful key). Injected into the page config; the FE loads the tracker
        and reports conversions on checkout. Off when unset."""
        return self._copy(_affiliate=api_key)

    def copy_public(self, *files: str):
        return self._copy(_copy_public=list(files))
