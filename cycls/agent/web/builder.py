"""cycls.Web — fluent immutable builder for chat UI / web surface config.

Holds auth, title, theme, billing plan, analytics, and public static files.
Passed to `@cycls.agent(web=...)` as a single composed object, or equivalent
fields can be passed directly on `@cycls.agent` for the simple case —
`web=` and direct chat kwargs are mutually exclusive.
"""
import base64
import mimetypes
from pathlib import Path
from typing import List, Optional

from cycls.app.auth import JWT


THEMES = ["default", "dev"]


def _asset(value: str) -> str:
    """Inline an image at build time: SVG paths as markup, PNG/JPG/WebP paths
    as data URIs (keep raster logos small — they ride the page config). Raw
    markup, URLs, and data: URIs pass through. Missing paths fail the build."""
    if value.lstrip().startswith("<") or value.startswith(("http://", "https://", "data:")):
        return value
    p = Path(value)
    if not p.is_file():
        raise ValueError(f"asset not found: {value}")
    if p.suffix.lower() == ".svg":
        return p.read_text()
    mime = mimetypes.guess_type(p.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"


class Web:
    def __init__(self):
        self._auth: Optional[JWT] = None
        self._iap = None
        self._title: Optional[str] = None
        self._theme: str = "default"
        self._cms: Optional[dict] = None
        self._analytics: bool = False
        self._suggestions: bool = False
        self._affiliate: Optional[str] = None
        self._max_upload: int = 512
        self._copy_public: List[str] = []
        self._workspaces: Optional[str] = None
        self._brand: dict = {}                    # locale → {name, description, logo}
        self._seo: Optional[dict] = None
        self._head: Optional[str] = None
        self._explore: Optional[list] = None
        self._og_bytes: Optional[bytes] = None
        self._og_url: Optional[str] = None
        self._favicon: Optional[str] = None
        self._colors: Optional[dict] = None

    def _copy(self, **updates):
        new = Web.__new__(Web)
        new.__dict__ = {**self.__dict__, **updates}
        return new

    def iap(self, config):
        """Apple In-App Purchase entitlements (see cycls.AppleIAP)."""
        return self._copy(_iap=config)

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

    def cms(self, *, brand: Optional[str] = None, explore: Optional[str] = None,
            token: Optional[str] = None):
        """Pull branding and/or the explore menu from any CMS: plain GET URLs
        returning the contract JSON (title/title_ar/description/description_ar/
        icon_svg; {"agents": [...]} for explore), optional bearer `token`.
        Static `.brand()` / `.explore()` win, piece by piece."""
        cms = {k: v for k, v in (("brand", brand), ("explore", explore), ("token", token)) if v}
        return self._copy(_cms=cms or None)

    def brand(self, locale="en", *, name=None, description=None, logo=None, brand=None, og=None, favicon=None):
        """Static branding, from code instead of a CMS. `name`, `description`,
        `logo` (the agent icon shown in the chat hero) and `brand` (the wordmark
        shown in the nav bar; falls back to the Cycls logo when unset) are per
        locale — repeat with `locale="ar"` for Arabic. `og` (social card, path
        or URL) and `favicon` apply globally. Image paths are read at build time
        (SVG inlined, PNG/JPG as data URIs), so assets don't need to ship with
        the container."""
        cur = {**self._brand.get(locale, {})}
        if name is not None: cur["name"] = name
        if description is not None: cur["description"] = description
        if logo is not None: cur["logo"] = _asset(logo)
        if brand is not None: cur["brand"] = _asset(brand)
        updates = {"_brand": {**self._brand, locale: cur}}
        if og is not None:
            if og.startswith(("http://", "https://")):
                updates["_og_url"] = og
            else:
                p = Path(og)
                if not p.is_file(): raise ValueError(f"og image not found: {og}")
                updates["_og_bytes"] = p.read_bytes()
        if favicon is not None: updates["_favicon"] = _asset(favicon)
        return self._copy(**updates)

    def colors(self, *, primary=None, secondary=None, primary_dark=None, secondary_dark=None):
        """Theme accent colors (any CSS color). `primary` drives highlights and
        active states, `secondary` chips and bubbles; the `_dark` variants
        override dark mode (default: same as light)."""
        cur = {**(self._colors or {})}
        for k, v in (("primary", primary), ("secondary", secondary),
                     ("primary_dark", primary_dark), ("secondary_dark", secondary_dark)):
            if v is not None: cur[k] = v
        return self._copy(_colors=cur)

    def seo(self, *, title=None, description=None):
        """Page/SEO copy when it should differ from the brand — the <title>
        tag, meta + og description. Defaults derive from the `en` brand."""
        cur = {**(self._seo or {})}
        if title is not None: cur["title"] = title
        if description is not None: cur["description"] = description
        return self._copy(_seo=cur)

    def head(self, html: str):
        """Append raw HTML to <head> — site verification, custom meta,
        anything the other knobs don't cover. Repeatable."""
        return self._copy(_head=(self._head or "") + html)

    def explore(self, *agents: dict):
        """Static explore menu (the agents dropdown). Each entry:
        {"name", "url", "logo"?, "name_ar"?, "description"?, "description_ar"?}.
        Overrides the CMS list; with neither, the menu is hidden."""
        out = []
        for a in agents:
            out.append({
                "slug": a.get("slug") or (a.get("name") or a.get("title", "")).lower().replace(" ", "-"),
                "title": a.get("name") or a.get("title", ""),
                "title_ar": a.get("name_ar") or a.get("title_ar"),
                "description": a.get("description", ""),
                "description_ar": a.get("description_ar"),
                "icon_svg": _asset(a["logo"]) if a.get("logo") else None,
                "link": a.get("url") or a.get("link", ""),
            })
        return self._copy(_explore=out)

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

    def workspaces(self, create: str = "member"):
        """Enable multi-workspace mode (docs/workspaces.md): every user gets a
        personal workspace, orgs get shared team workspaces with role-based
        access; the active one is selected per request via the `X-Workspace`
        header. Requires `auth(...)`. `create` sets who may create team
        workspaces: "member" (default) or "admin" (org admins only)."""
        if create not in ("member", "admin"):
            raise ValueError(f'workspaces create must be "member" or "admin"; got {create!r}')
        return self._copy(_workspaces=create)

    def max_upload(self, mb: int):
        """Per-file upload cap in MB (default 512). Enforced server-side and
        pre-checked client-side so oversized files fail fast."""
        return self._copy(_max_upload=mb)

    def copy_public(self, *files: str):
        return self._copy(_copy_public=list(files))
