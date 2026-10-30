"""ntfy.sh push notification helper for Farro Fresh scraper."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import urllib.request
from typing import Optional

DEFAULT_TOPIC_ENV = "NTFY_TOPIC"
DEFAULT_BASE = "https://ntfy.sh"
_ENV_PATH = Path(__file__).resolve().parent / ".env"


def _get_topic() -> Optional[str]:
    topic = os.environ.get(DEFAULT_TOPIC_ENV)
    if not topic and _ENV_PATH.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(_ENV_PATH)
            topic = os.environ.get(DEFAULT_TOPIC_ENV)
        except Exception:
            pass
    return topic


def push(message: str, title: Optional[str] = None, priority: str = "default",
         tags: Optional[list[str]] = None, topic: Optional[str] = None) -> bool:
    """POST a message to ntfy.sh."""
    topic = topic or _get_topic()
    if not topic:
        return False

    url = f"{DEFAULT_BASE}/{topic}"
    headers = {"Priority": priority}
    if title:
        headers["Title"] = title.encode("ascii", "replace").decode("ascii")
    if tags:
        headers["Tags"] = ",".join(tags)

    try:
        req = urllib.request.Request(
            url,
            data=message.encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except Exception as exc:
        sys.stderr.write(f"[notify] push failed: {exc}\n")
        return False
