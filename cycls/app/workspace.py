"""Workspace — per-tenant root + slatedb data dir + url() resolver.

A `Workspace` packages three things for one tenant: a filesystem root, an
embedded-DB data directory, and the URL where that data lives (gs://... or
file://...). It's the bridge between identity (subject) and storage (URL),
nothing more — `cycls.DB` consumes the URL and doesn't import this module.
"""
from pathlib import Path


class Workspace:
    """Per-tenant root + slatedb data dir under *volume*. *tenant* is `user_id`
    for personal users or `org_id/user_id` for org members — the same string
    `subject_for(user)` returns. Signed-URL subjects round-trip through this
    constructor, so it's the single source of truth for tenant→path mapping."""

    def __init__(self, volume, tenant, bucket=None):
        self.volume = Path(volume)
        self.tenant = tenant
        if "/" in tenant:
            org_id, user_id = tenant.split("/", 1)
            self.root = self.volume / org_id
            self.data = self.root / ".cycls" / user_id
        else:
            self.root = self.volume / tenant
            self.data = self.root / ".cycls"
        self._bucket = bucket

    def url(self) -> str:
        if self._bucket:
            return f"{self._bucket.rstrip('/')}/{self.data.relative_to(self.volume)}"
        return f"file://{self.data}"


def subject_for(user) -> str:
    """`user_id` for personal users, `org_id/user_id` for org members. The
    string round-trips through `Workspace(volume, ..., bucket)`."""
    return f"{user.org_id}/{user.id}" if getattr(user, "org_id", None) else user.id


def workspace_for(user, volume, bucket=None):
    """Build a Workspace for *user* under *volume*. None → /local; org member →
    /<org>/.cycls/<user>; personal → /<user>/.cycls."""
    return Workspace(volume, "local" if user is None else subject_for(user), bucket=bucket)
