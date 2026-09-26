"""
reply_handler.py

Handles /v1/reply — fully deterministic, no external LLM.

Decision tree:
  1. Opt-out / hostile        -> action=end
  2. Auto-reply detection     -> send (flag owner) / wait / end
  3. Wait request             -> action=wait
  4. Affirmative intent       -> action=send (concrete next step, no qualifying)
  5. Off-topic question       -> action=send (polite redirect)
  6. General continuation     -> action=send (acknowledge + advance)
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

URL_PATTERN = re.compile(r'https?://\S+|www\.\S+', re.IGNORECASE)

# ---------------------------------------------------------------------------
# Detection phrase lists
# ---------------------------------------------------------------------------

AUTO_REPLY_PHRASES = [
    "thank you for contacting",
    "aapki jaankari ke liye bahut-bahut shukriya",
    "our team will respond",
    "automated assistant",
    "we will get back",
    "we'll get back",
    "hum jald hi",
    "yeh ek automated",
    "this is an automated",
    "sorry i am currently unavailable",
    "i am away",
    "i'm away",
    "aapka sandesh mil gaya",
    "आपकी जानकारी के लिए",
]

OPT_OUT_PHRASES = [
    "stop messaging", "stop sending",
    "not interested", "don't message", "dont message",
    "remove me", "unsubscribe",
    "band karo", "mat bhejo", "nahi chahiye",
    "useless spam", "bothering me",
    "blocking you", "report you",
]

AFFIRMATIVE_PHRASES = [
    "yes please", "yes go ahead", "ok let's do it", "lets do it",
    "let's do it", "go ahead", "please proceed",
    "sounds good", "do it", "proceed", "please send",
    "send me", "what's next", "whats next", "zaroor", "bilkul",
]

AFFIRMATIVE_EXACT = {"yes", "y", "ok", "okay", "sure", "haan", "ha", "bilkul"}

WAIT_PHRASES = [
    "call me later", "not now", "busy right now",
    "will check later", "let me think", "give me some time",
    "abhi nahi", "baad mein", "thodi der mein",
]

OFF_TOPIC_SIGNALS = [
    "gst filing", "income tax", "legal", "court", "police",
    "insurance", "loan", "emi", "passport", "visa",
]


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    return text.lower().strip()


def detect_auto_reply(message: str, prior_bodies: List[str]) -> bool:
    norm = _norm(message)
    if any(p in norm for p in AUTO_REPLY_PHRASES):
        return True
    # Exact verbatim repeat
    return message.strip() in [b.strip() for b in prior_bodies]


def count_consecutive_auto_replies(turns: List[Dict[str, Any]]) -> int:
    merchant_turns = [t for t in turns if t.get("from") in ("merchant", "customer")]
    if not merchant_turns:
        return 0
    count = 0
    prior: List[str] = []
    for t in merchant_turns:
        body = t.get("body", "")
        if detect_auto_reply(body, prior):
            count += 1
        else:
            count = 0
        prior.append(body)
    return count


def detect_opt_out(message: str) -> bool:
    norm = _norm(message)
    # Single-word hard stops
    if norm in ("stop", "no", "nahi", "nope", "never"):
        return False  # "no" alone isn't always opt-out; context needed
    return any(p in norm for p in OPT_OUT_PHRASES)


def detect_affirmative(message: str) -> bool:
    norm = _norm(message)
    if norm in AFFIRMATIVE_EXACT:
        return True
    return any(p in norm for p in AFFIRMATIVE_PHRASES)


def detect_wait_request(message: str) -> bool:
    return any(p in _norm(message) for p in WAIT_PHRASES)


def detect_off_topic(message: str) -> bool:
    return any(p in _norm(message) for p in OFF_TOPIC_SIGNALS)


# ---------------------------------------------------------------------------
# Rule-based reply builder
# ---------------------------------------------------------------------------

def _build_affirmative_reply(
    merchant: Dict[str, Any],
    trigger: Dict[str, Any],
    turns: List[Dict[str, Any]],
    customer: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Merchant committed — immediately execute the next concrete step."""
    kind = trigger.get("kind", "")
    owner = _owner(merchant)
    mname = _mname(merchant)
    offer = _active_offer(merchant)
    payload = trigger.get("payload", {})

    # --- Kind-specific action responses ---
    if kind == "research_digest":
        body = (
            f"Sending the summary now. Also drafting a patient-education WhatsApp "
            f"you can forward to your patient list — ready in 60 seconds. "
            f"Want me to schedule it as a GBP post too? Reply YES/NO."
        )
        cta = "binary_yes_no"

    elif kind == "regulation_change":
        body = (
            f"Here's your compliance checklist — 3 steps: "
            f"(1) audit current setup against new limit, "
            f"(2) document updated SOP, "
            f"(3) confirm before deadline. "
            f"Want me to draft the SOP template? Reply YES."
        )
        cta = "binary_yes_no"

    elif kind == "active_planning_intent":
        topic = payload.get("intent_topic", "").replace("_", " ")
        body = (
            f"On it — drafting the full {topic} structure for {mname} now. "
            f"I'll include tiered pricing, delivery window, and a 3-line outreach message. "
            f"Confirm once done? Reply YES."
        )
        cta = "binary_yes_no"

    elif kind == "festival_upcoming":
        festival = payload.get("festival", "the festival")
        body = (
            f"Drafting the {festival} GBP post + WhatsApp blast now. "
            f"I'll use your active offer{' ' + offer if offer else ''} as the hook. "
            f"Ready to review in 2 minutes — confirm? Reply YES."
        )
        cta = "binary_yes_no"

    elif kind == "ipl_match_today":
        body = (
            f"Drafting the Swiggy banner + Insta story now. "
            f"Using your {offer or 'current offer'} as the feature. Live in 10 minutes. "
            f"Confirm send? Reply YES."
        )
        cta = "binary_yes_no"

    elif kind == "review_theme_emerged":
        theme = payload.get("theme", "").replace("_", " ")
        body = (
            f"Drafting a response template for the '{theme}' reviews + one operational fix suggestion. "
            f"Will send both in 2 minutes. Confirm? Reply YES."
        )
        cta = "binary_yes_no"

    elif kind == "supply_alert":
        molecule = payload.get("molecule", "the medication")
        body = (
            f"Pulling the affected customer list for {molecule} now. "
            f"Will have the WhatsApp draft + replacement workflow ready in 2 minutes. "
            f"Confirm send? Reply YES."
        )
        cta = "binary_yes_no"

    elif kind in ("customer_lapsed_soft", "customer_lapsed_hard", "trial_followup"):
        cname = _cust_name(customer) if customer else ""
        booking_subject = ("Booking " + cname + "'s") if cname else "Booking the"
        offer_line = ("Using " + offer + " as the incentive. ") if offer else ""
        body = (
            f"{booking_subject} trial slot now. "
            f"{offer_line}"
            f"Confirm I can send the booking confirmation? Reply YES."
        )
        cta = "binary_yes_no"

    elif kind == "renewal_due":
        plan = payload.get("plan", "Pro")
        amount = payload.get("renewal_amount")
        amount_str = f" ₹{amount:,}" if amount else ""
        body = (
            f"Initiating {plan} renewal{amount_str}. "
            f"Your profile and offers stay live uninterrupted. "
            f"You'll get a confirmation shortly."
        )
        cta = "none"

    elif kind == "gbp_unverified":
        path = payload.get("verification_path", "postcard or phone call")
        body = (
            f"Starting GBP verification via {path}. "
            f"Step 1: confirm the business phone number on your profile is reachable. Is it correct?"
        )
        cta = "binary_yes_no"

    else:
        # Generic affirmative action
        body = (
            f"On it — drafting now and will share in the next 2 minutes. "
            f"{'Using your ' + offer + ' as the anchor.' if offer else ''}"
        )
        cta = "open_ended"

    return {"action": "send", "body": body, "cta": cta,
            "rationale": f"Merchant committed (affirmative). Switching to action mode for {kind}."}


def _build_continuation_reply(
    message: str,
    merchant: Dict[str, Any],
    trigger: Dict[str, Any],
    turns: List[Dict[str, Any]],
    customer: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Handle questions and general continuation without qualifying further."""
    kind = trigger.get("kind", "")
    owner = _owner(merchant)
    offer = _active_offer(merchant)
    norm = _norm(message)

    # Off-topic redirect
    if detect_off_topic(message):
        prev_topic = kind.replace("_", " ") if kind else "what we were discussing"
        body = (
            f"That's outside what I can help with directly — "
            f"best to check with your CA or relevant authority. "
            f"Coming back to {prev_topic} — want to continue from where we left off? Reply YES."
        )
        return {"action": "send", "body": body, "cta": "binary_yes_no",
                "rationale": "Off-topic request politely declined; redirected to original topic."}

    # Question about pricing / offer
    if any(w in norm for w in ("price", "cost", "how much", "kitna", "rate")):
        if offer:
            body = (
                f"Your current active offer is: {offer}. "
                f"Want me to draft a pricing breakdown or update the offer? Reply YES."
            )
        else:
            body = (
                f"You don't have an active offer set right now. "
                f"Want me to draft one based on your category's best-performing formats? Reply YES."
            )
        return {"action": "send", "body": body, "cta": "binary_yes_no",
                "rationale": "Pricing question answered using active offer from merchant context."}

    # Question about timing / when
    if any(w in norm for w in ("when", "kab", "how long", "kitni der")):
        body = (
            f"Typically takes 2–5 minutes on my end. "
            f"Want me to proceed now? Reply YES."
        )
        return {"action": "send", "body": body, "cta": "binary_yes_no",
                "rationale": "Timing question answered with generic estimate."}

    # Anything else — acknowledge and offer to proceed
    turn_count = len([t for t in turns if t.get("from") == "vera"])
    if turn_count >= 4:
        # After 4 vera turns with no clear outcome, gracefully offer to close
        body = (
            f"Happy to help further — just say the word whenever you're ready. "
            f"If you want to pick this up later, reply YES and I'll come back tomorrow."
        )
        return {"action": "send", "body": body, "cta": "binary_yes_no",
                "rationale": "Conversation extended without clear outcome; offering graceful pause."}

    body = (
        f"Got it. {'Using your ' + offer + ' as the starting point. ' if offer else ''}"
        f"Want me to draft the next step and send it over? Reply YES."
    )
    return {"action": "send", "body": body, "cta": "binary_yes_no",
            "rationale": "General continuation; offered concrete next step."}


# ---------------------------------------------------------------------------
# Helpers (local, no import from composer to avoid circular deps)
# ---------------------------------------------------------------------------

def _owner(merchant: Dict[str, Any]) -> str:
    identity = merchant.get("identity", {})
    return identity.get("owner_first_name") or identity.get("name", "there")


def _mname(merchant: Dict[str, Any]) -> str:
    return merchant.get("identity", {}).get("name", "your business")


def _active_offer(merchant: Dict[str, Any]) -> str:
    for o in merchant.get("offers", []):
        if o.get("status") == "active":
            return o.get("title", "")
    return ""


def _cust_name(customer: Dict[str, Any]) -> str:
    return customer.get("identity", {}).get("name", "")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def compose_reply(
    conversation_id: str,
    merchant_message: str,
    turns: List[Dict[str, Any]],
    merchant: Dict[str, Any],
    category: Dict[str, Any],
    trigger: Dict[str, Any],
    customer: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Decide the next action given a merchant/customer reply.
    Fully deterministic — no external calls.
    Returns dict with: action, body (optional), cta, rationale.
    """

    # 1. Opt-out
    if detect_opt_out(merchant_message):
        return {
            "action": "end",
            "rationale": "Merchant explicitly opted out. Closing conversation.",
        }

    # 2. Auto-reply detection
    all_turns = turns + [{"from": "merchant", "body": merchant_message}]
    auto_count = count_consecutive_auto_replies(all_turns)

    if auto_count >= 3:
        return {
            "action": "end",
            "rationale": f"Auto-reply detected {auto_count} times in a row. Closing — no real engagement.",
        }
    if auto_count == 2:
        return {
            "action": "wait",
            "wait_seconds": 86400,
            "rationale": "Auto-reply twice in a row. Owner not available. Waiting 24h.",
        }
    if auto_count == 1:
        owner = _owner(merchant)
        body = (
            f"Looks like an auto-reply 😊 "
            f"{'Hi ' + owner + ', ' if owner else ''}"
            f"when you get a moment, just reply YES to continue."
        )
        return {
            "action": "send",
            "body": body,
            "cta": "binary_yes_no",
            "rationale": "First auto-reply detected. One prompt to reach the real owner.",
        }

    # 3. Wait request
    if detect_wait_request(merchant_message):
        return {
            "action": "wait",
            "wait_seconds": 1800,
            "rationale": "Merchant asked for more time. Backing off 30 min.",
        }

    # 4. Affirmative intent → immediate action, no qualifying
    if detect_affirmative(merchant_message):
        return _build_affirmative_reply(merchant, trigger, turns, customer)

    # 5. Off-topic / general continuation
    return _build_continuation_reply(merchant_message, merchant, trigger, turns, customer)
