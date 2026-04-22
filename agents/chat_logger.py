"""
chat_logger.py — Shared LLM turn logger for all agent sessions.

Usage:
    from agents.chat_logger import ChatLogger
    logger = ChatLogger()                    # one instance per session
    logger.log(actor="lead", request=_req, response=response)

Each session writes to:
    .models/chat_logs_<YYYY-MM-DD_HH-MM-SS>_<session_id>.jsonl
"""

import datetime
import json
import threading
import uuid
from pathlib import Path


def _serializable_messages(messages: list) -> list:
    """Return a JSON-safe copy of a messages list, converting SDK objects to dicts."""
    out = []
    for m in messages:
        m2 = {k: v for k, v in m.items() if k != "tool_calls"}
        if m.get("tool_calls"):
            m2["tool_calls"] = [
                {"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments}
                if hasattr(tc, "function")
                else tc
                for tc in m["tool_calls"]
            ]
        out.append(m2)
    return out


class ChatLogger:
    """One instance per agent session. Thread-safe JSONL writer."""

    def __init__(self, log_dir: str | Path = ".models"):
        self.session_id = uuid.uuid4().hex[:8]
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        self.log_file = self.log_dir / f"chat_logs_{ts}_{self.session_id}.jsonl"
        self._lock = threading.Lock()
        print(f"[session {self.session_id}] logging to {self.log_file}")

    def log(self, actor: str, request: list, response, model: str = "") -> None:
        """Append one LLM turn (request + response) to the session JSONL log."""
        msg = response.choices[0].message
        tool_calls_data = None
        if msg.tool_calls:
            tool_calls_data = [
                {"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments}
                for tc in msg.tool_calls
            ]
        entry = {
            "ts": datetime.datetime.now().isoformat(),
            "session_id": self.session_id,
            "actor": actor,
            "model": model,
            "request": _serializable_messages(request),
            "response": {
                "content": msg.content,
                "tool_calls": tool_calls_data,
                "finish_reason": response.choices[0].finish_reason,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                } if response.usage else None,
            },
        }
        with self._lock:
            with self.log_file.open("a") as f:
                f.write(json.dumps(entry) + "\n")
