"""Browser automation for Cycls agents — thin client to a shared real-Chrome
service (Steel Browser or a managed provider), connected over CDP. See
docs/notes/browser.md."""
from .client import Session, Unavailable, configured, session

__all__ = ["Session", "Unavailable", "configured", "session"]
