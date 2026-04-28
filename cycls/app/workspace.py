"""Workspace — pointer at a tenant's filesystem root + slatedb URL.

A `Workspace` is a frozen value: `(root, url)`. `workspace_for` builds one
from a User; `workspace_at` builds one from a tenant string (e.g. the
subject in a signed URL). Both are inverses through `subject_for`.
"""
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Workspace:
    root: Path
    url: str


def subject_for(user) -> str:
    """`user_id` for personal users, `org_id/user_id` for org members. The
    string round-trips through `workspace_at`."""
    return f"{user.org_id}/{user.id}" if getattr(user, "org_id", None) else user.id


def workspace_for(user, volume, bucket=None) -> Workspace:
    """Workspace for *user* under *volume*. None → /local; org member →
    /<org>/.cycls/<user>; personal → /<user>/.cycls."""
    return workspace_at("local" if user is None else subject_for(user), volume, bucket)


def workspace_at(tenant, volume, bucket=None) -> Workspace:
    """Workspace from a tenant string (e.g. a signed-URL subject)."""
    volume = Path(volume)
    if "/" in tenant:
        org, user = tenant.split("/", 1)
        root = volume / org
        data = root / ".cycls" / user
    else:
        root = volume / tenant
        data = root / ".cycls"
    url = (f"{bucket.rstrip('/')}/{data.relative_to(volume)}"
           if bucket else f"file://{data}")
    return Workspace(root=root, url=url)
