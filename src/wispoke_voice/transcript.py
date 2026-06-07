"""
Live transcript collection for a voice session.

The old approach scraped `session.history` at the end of the call and guessed
at attribute shapes. On livekit-agents 1.5 the supported path is the
`conversation_item_added` event, which fires once per finalized turn and
carries a wall-clock `created_at`. We subscribe to it so we can record a
**timestamped** transcript — the dashboard uses the `t` offset to seek the
recording to the moment each line was spoken.

Each entry is `{"role": ..., "content": ..., "t": <seconds-from-call-start>}`.
We keep only spoken message turns (user / assistant); tool calls and their
outputs are dropped so the transcript reads like a conversation.
"""

from __future__ import annotations

import datetime as _dt
import time
from typing import Any, Dict, List, Optional

from livekit.agents import AgentSession, ConversationItemAddedEvent

from wispoke_voice.observability import get_logger

logger = get_logger("wispoke.voice.transcript")


def _flatten_content(content: Any) -> str:
    """Collapse a message's content into a single string.

    Text messages carry `content` as a list of strings; non-text parts
    (images, audio) are skipped — they can't go in a text transcript.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        return " ".join(c for c in content if isinstance(c, str)).strip()
    return str(content)


def _epoch(v: Any) -> Optional[float]:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, _dt.datetime):
        return v.timestamp()
    return None


class TranscriptCollector:
    """Accumulates conversation turns with timestamps relative to call start."""

    __slots__ = ("_start", "_entries")

    def __init__(self) -> None:
        self._start = time.time()
        self._entries: List[Dict[str, Any]] = []

    def attach(self, session: AgentSession) -> None:
        """Wire the event handler. Call BEFORE `session.start` so the agent's
        greeting (spoken in `on_enter`) is captured too."""

        @session.on("conversation_item_added")
        def _on_item(ev: ConversationItemAddedEvent) -> None:  # noqa: ANN202
            try:
                item = ev.item
                # Only spoken message turns — skip function_call / outputs.
                if getattr(item, "type", "message") != "message":
                    return
                text = _flatten_content(getattr(item, "content", None))
                if not text:
                    return
                role = getattr(item, "role", None) or "system"
                entry: Dict[str, Any] = {"role": str(role), "content": text}
                started = _epoch(getattr(ev, "created_at", None))
                if started is not None:
                    entry["t"] = round(max(0.0, started - self._start), 2)
                self._entries.append(entry)
            except Exception:
                # A transcript hiccup must never break the live session.
                logger.exception("failed to record transcript item")

    def entries(self) -> List[Dict[str, Any]]:
        """Snapshot of the transcript so far (safe to call in the finally block)."""
        return list(self._entries)
