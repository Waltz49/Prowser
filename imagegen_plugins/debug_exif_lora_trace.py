"""Temporary debug tracing for EXIF LoRA import (session 1a9fc9)."""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

_LOG_PATH = "/Users/douglasnadel/dev/testchat/image_browser/.cursor/debug-1a9fc9.log"
_SESSION_ID = "1a9fc9"


def agent_exif_lora_dbg(
    hypothesis_id: str,
    location: str,
    message: str,
    data: Optional[Dict[str, Any]] = None,
) -> None:
    # #region agent log
    try:
        payload = {
            "sessionId": _SESSION_ID,
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data or {},
            "timestamp": int(time.time() * 1000),
        }
        with open(_LOG_PATH, "a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(payload, default=str) + "\n")
    except Exception:
        pass
    # #endregion
