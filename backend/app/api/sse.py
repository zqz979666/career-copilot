"""Server-Sent Events helpers."""
from __future__ import annotations

import json
from typing import Any


def sse(event: str, data: Any) -> str:
    """Serialize a single SSE frame.

    All payloads are JSON-encoded so consumers can safely
    ``JSON.parse(evt.data)`` regardless of embedded newlines or quotes.
    """
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


SSE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # Nginx: don't buffer
}
