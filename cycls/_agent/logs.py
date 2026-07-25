import json
from datetime import datetime, timezone


def log(level, *, user=None, chat_id=None, **fields):
    print(json.dumps({
        "source": "agent", "level": level,
        "at": datetime.now(timezone.utc).isoformat(),
        "user_id": getattr(user, "id", None),
        "org_id": getattr(user, "org_id", None),
        "plan": getattr(user, "plan", None),
        "chat_id": chat_id, **fields,
    }), flush=True)
