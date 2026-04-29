"""Workspace — per-tenant `(root, path, base)`."""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class Workspace:
    root: Path
    path: str
    base: Optional[str] = None


def subject_for(user) -> str:
    return f"{user.org_id}/{user.id}" if getattr(user, "org_id", None) else user.id


def workspace_for(user, volume, base=None) -> Workspace:
    return workspace_at("local" if user is None else subject_for(user), volume, base)


def workspace_at(tenant, volume, base=None) -> Workspace:
    volume = Path(volume)
    if "/" in tenant:
        org, user = tenant.split("/", 1)
        return Workspace(root=volume / org, path=f"{org}/.db/{user}", base=base)
    return Workspace(root=volume / tenant, path=f"{tenant}/.db", base=base)
