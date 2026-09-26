"""
Shared in-memory state for the VERA bot.
All stores are module-level so they persist across requests within a single process.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Set, Tuple

# (scope, context_id) -> {"version": int, "payload": dict}
contexts: Dict[Tuple[str, str], Dict[str, Any]] = {}

# conversation_id -> list of turn dicts {from, body, ts, action}
conversations: Dict[str, List[Dict[str, Any]]] = {}

# suppression_key -> bool  (True = already sent, don't repeat)
sent_suppression_keys: Set[str] = set()

# Process start time for uptime reporting
START_TIME: float = time.time()


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def get_payload(scope: str, context_id: str) -> Optional[Dict[str, Any]]:
    entry = contexts.get((scope, context_id))
    return entry["payload"] if entry else None


def get_version(scope: str, context_id: str) -> int:
    entry = contexts.get((scope, context_id))
    return entry["version"] if entry else 0


def store_context(scope: str, context_id: str, version: int, payload: Dict[str, Any]) -> None:
    contexts[(scope, context_id)] = {"version": version, "payload": payload}


def count_by_scope() -> Dict[str, int]:
    counts: Dict[str, int] = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
    for (scope, _) in contexts:
        if scope in counts:
            counts[scope] += 1
    return counts


def append_turn(conversation_id: str, from_role: str, body: str, action: str = "send") -> None:
    conversations.setdefault(conversation_id, []).append(
        {"from": from_role, "body": body, "action": action}
    )


def get_turns(conversation_id: str) -> List[Dict[str, Any]]:
    return conversations.get(conversation_id, [])


def is_suppressed(key: str) -> bool:
    return key in sent_suppression_keys


def suppress(key: str) -> None:
    sent_suppression_keys.add(key)
