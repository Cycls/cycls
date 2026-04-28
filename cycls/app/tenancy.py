"""Workspace — pointer at a tenant's filesystem layout.

A `Workspace` is a frozen value:
    volume — mount root for the deployment (e.g. /workspace)
    root   — fs root for this tenant (= volume/<tenant>)
    data   — framework-reserved subdir under root (= root/.db[/user])
    bucket — optional object-store prefix (e.g. gs://cycls-ws-foo)

Workspace doesn't know how to *format* a URL — that's a `db.py` concern,
since URL syntax (file://, gs://) is storage-backend-specific. Workspace
only knows the convention that the framework reserves `<root>/.db` for
its per-tenant managed state.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class Workspace:
    volume: Path
    root: Path
    data: Path
    bucket: Optional[str] = None


def subject_for(user) -> str:
    """`user_id` for personal users, `org_id/user_id` for org members. The
    string round-trips through `workspace_at`."""
    return f"{user.org_id}/{user.id}" if getattr(user, "org_id", None) else user.id


def workspace_for(user, volume, bucket=None) -> Workspace:
    """Workspace for *user* under *volume*. None → /local; org member →
    /<org>/.db/<user>; personal → /<user>/.db."""
    return workspace_at("local" if user is None else subject_for(user), volume, bucket)


def workspace_at(tenant, volume, bucket=None) -> Workspace:
    """Workspace from a tenant string (e.g. a signed-URL subject)."""
    volume = Path(volume)
    if "/" in tenant:
        org, user = tenant.split("/", 1)
        root = volume / org
        data = root / ".db" / user
    else:
        root = volume / tenant
        data = root / ".db"
    return Workspace(volume=volume, root=root, data=data, bucket=bucket)
