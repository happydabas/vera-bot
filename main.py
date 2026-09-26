"""
VERA Bot — main FastAPI application.

Endpoints:
    GET  /v1/healthz
    GET  /v1/metadata
    POST /v1/context
    POST /v1/tick
    POST /v1/reply
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel, Field

load_dotenv()

import state
from composer import compose
from reply_handler import compose_reply

app = FastAPI(title="VERA Bot", version=os.getenv("BOT_VERSION", "1.0.0"))

# ---------------------------------------------------------------------------
# /v1/healthz
# ---------------------------------------------------------------------------

@app.get("/v1/healthz")
async def healthz() -> Dict[str, Any]:
    counts = state.count_by_scope()
    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - state.START_TIME),
        "contexts_loaded": counts,
    }


# ---------------------------------------------------------------------------
# /v1/metadata
# ---------------------------------------------------------------------------

@app.get("/v1/metadata")
async def metadata() -> Dict[str, Any]:
    members_raw = os.getenv("TEAM_MEMBERS", "Builder")
    members = [m.strip() for m in members_raw.split(",")]
    return {
        "team_name": os.getenv("TEAM_NAME", "TeamVera"),
        "team_members": members,
        "model": "rule-based deterministic composer",
        "approach": (
            "Deterministic 4-context composer (category + merchant + trigger + customer). "
            "Per-trigger-kind message templates grounded in supplied context. "
            "Rule-based auto-reply detection, intent-transition routing, no external LLM."
        ),
        "contact_email": os.getenv("CONTACT_EMAIL", "team@example.com"),
        "version": os.getenv("BOT_VERSION", "1.0.0"),
        "submitted_at": "2026-04-26T08:00:00Z",
    }


# ---------------------------------------------------------------------------
# /v1/context
# ---------------------------------------------------------------------------

class ContextBody(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: Dict[str, Any]
    delivered_at: str = ""

VALID_SCOPES = {"category", "merchant", "customer", "trigger"}

@app.post("/v1/context")
async def push_context(body: ContextBody) -> Dict[str, Any]:
    if body.scope not in VALID_SCOPES:
        return {
            "accepted": False,
            "reason": "invalid_scope",
            "details": f"scope must be one of {sorted(VALID_SCOPES)}",
        }

    current_version = state.get_version(body.scope, body.context_id)
    if current_version >= body.version:
        # Idempotent — same version is a no-op; lower current means higher version exists
        return {
            "accepted": False,
            "reason": "stale_version",
            "current_version": current_version,
        }

    state.store_context(body.scope, body.context_id, body.version, body.payload)
    return {
        "accepted": True,
        "ack_id": f"ack_{body.context_id}_v{body.version}",
        "stored_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


# ---------------------------------------------------------------------------
# /v1/tick
# ---------------------------------------------------------------------------

class TickBody(BaseModel):
    now: str
    available_triggers: List[str] = Field(default_factory=list)

@app.post("/v1/tick")
async def tick(body: TickBody) -> Dict[str, Any]:
    actions: List[Dict[str, Any]] = []

    for trg_id in body.available_triggers:
        try:
            action = _process_trigger(trg_id)
            if action:
                actions.append(action)
        except Exception:
            # Never let one trigger crash the whole tick
            continue

    return {"actions": actions}


def _process_trigger(trg_id: str) -> Optional[Dict[str, Any]]:
    """Attempt to compose and return an action for a trigger. Returns None to skip."""
    trigger = state.get_payload("trigger", trg_id)
    if not trigger:
        return None

    # Check suppression
    suppression_key = trigger.get("suppression_key", "")
    if suppression_key and state.is_suppressed(suppression_key):
        return None

    merchant_id = trigger.get("merchant_id")
    if not merchant_id:
        return None

    merchant = state.get_payload("merchant", merchant_id)
    if not merchant:
        return None

    category_slug = merchant.get("category_slug", "")
    category = state.get_payload("category", category_slug)
    if not category:
        return None

    # Optional customer
    customer_id = trigger.get("customer_id")
    customer = state.get_payload("customer", customer_id) if customer_id else None

    # Build conversation ID deterministically so we can resume it
    conv_id = f"conv_{merchant_id}_{trg_id}"

    # Skip if there's already an open conversation on this topic
    existing_turns = state.get_turns(conv_id)
    if existing_turns:
        # Already started — don't re-initiate on tick
        return None

    # Compose
    result = compose(category, merchant, trigger, customer)

    # Record the outbound turn
    state.append_turn(conv_id, "vera", result["body"], "send")

    # Suppress this key so we don't re-send on next tick
    if suppression_key:
        state.suppress(suppression_key)

    action: Dict[str, Any] = {
        "conversation_id": conv_id,
        "merchant_id": merchant_id,
        "customer_id": customer_id,
        "send_as": result.get("send_as", "vera"),
        "trigger_id": trg_id,
        "template_name": result.get("template_name", "vera_generic_v1"),
        "template_params": result.get("template_params", []),
        "body": result["body"],
        "cta": result.get("cta", "open_ended"),
        "suppression_key": result.get("suppression_key", suppression_key),
        "rationale": result.get("rationale", ""),
    }
    return action


# ---------------------------------------------------------------------------
# /v1/reply
# ---------------------------------------------------------------------------

class ReplyBody(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str = "merchant"
    message: str
    received_at: str = ""
    turn_number: int = 2

@app.post("/v1/reply")
async def reply(body: ReplyBody) -> Dict[str, Any]:
    conv_id = body.conversation_id

    # Record inbound turn
    state.append_turn(conv_id, body.from_role, body.message, "received")
    turns = state.get_turns(conv_id)

    # Resolve context from stored state
    merchant_id = body.merchant_id or _infer_merchant_from_conv(conv_id)
    merchant = state.get_payload("merchant", merchant_id) if merchant_id else {}
    category: Dict[str, Any] = {}
    trigger: Dict[str, Any] = {}
    customer: Optional[Dict[str, Any]] = None

    if merchant:
        category = state.get_payload("category", merchant.get("category_slug", "")) or {}

    # Find trigger from conversation ID heuristic (conv_{merchant_id}_{trg_id})
    if merchant_id and "_" in conv_id:
        # conv_id format: conv_{merchant_id}_{trg_id}
        rest = conv_id[len("conv_"):]          # removeprefix not needed; str slicing works on 3.9
        expected_prefix = merchant_id + "_"
        if rest.startswith(expected_prefix):
            trg_id = rest[len(expected_prefix):]
            trigger = state.get_payload("trigger", trg_id) or {}

    if body.customer_id:
        customer = state.get_payload("customer", body.customer_id)

    result = compose_reply(
        conversation_id=conv_id,
        merchant_message=body.message,
        turns=turns,
        merchant=merchant or {},
        category=category or {},
        trigger=trigger or {},
        customer=customer,
    )

    # Record outbound turn and return
    action = result.get("action", "send")
    if action == "send":
        out_body = result.get("body", "")
        state.append_turn(conv_id, "vera", out_body, "send")
        return {
            "action": "send",
            "body": out_body,
            "cta": result.get("cta", "open_ended"),
            "rationale": result.get("rationale", ""),
        }
    elif action == "wait":
        state.append_turn(conv_id, "vera", "[waiting]", "wait")
        return {
            "action": "wait",
            "wait_seconds": result.get("wait_seconds", 1800),
            "rationale": result.get("rationale", ""),
        }
    else:  # end
        state.append_turn(conv_id, "vera", "[ended]", "end")
        return {
            "action": "end",
            "rationale": result.get("rationale", "Conversation ended."),
        }


def _infer_merchant_from_conv(conv_id: str) -> Optional[str]:
    """Try to extract merchant_id from a conversation_id like conv_{merchant_id}_{trg_id}."""
    if not conv_id.startswith("conv_"):
        return None
    rest = conv_id[len("conv_"):]
    # All merchant IDs in the dataset start with m_
    for (scope, cid) in state.contexts:
        if scope == "merchant" and rest.startswith(cid):
            return cid
    # Fallback: try first 3-segment match (e.g. m_001_drmeera)
    parts = rest.split("_")
    if len(parts) >= 3 and parts[0] == "m":
        candidate = "_".join(parts[:3])
        if state.get_payload("merchant", candidate):
            return candidate
    return None


# ---------------------------------------------------------------------------
# Optional teardown
# ---------------------------------------------------------------------------

@app.post("/v1/teardown")
async def teardown() -> Dict[str, Any]:
    state.contexts.clear()
    state.conversations.clear()
    state.sent_suppression_keys.clear()
    return {"torn_down": True}
