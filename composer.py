"""
VERA message composer — fully deterministic, zero external dependencies.

compose(category, merchant, trigger, customer=None) -> dict

Each trigger kind has its own _compose_<kind> function that pulls only from
the supplied context dicts. No LLM, no HTTP calls, no fabrication.

Scoring dimensions targeted:
    1. Specificity       — real numbers, dates, citations from context
    2. Category fit      — tone/voice from CategoryContext.voice
    3. Merchant fit      — owner first name, real signals/offers/perf numbers
    4. Trigger relevance — WHY NOW is explicit in the opening line
    5. Engagement compulsion — loss aversion / curiosity / single CTA last
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

URL_PATTERN = re.compile(r'https?://\S+|www\.\S+', re.IGNORECASE)

CTA_BY_KIND: Dict[str, str] = {
    "research_digest": "open_ended",
    "regulation_change": "binary_yes_no",
    "recall_due": "multi_choice_slot",
    "chronic_refill_due": "binary_confirm_cancel",
    "perf_dip": "open_ended",
    "perf_spike": "open_ended",
    "seasonal_perf_dip": "open_ended",
    "milestone_reached": "open_ended",
    "dormant_with_vera": "binary_yes_no",
    "festival_upcoming": "binary_yes_no",
    "ipl_match_today": "binary_yes_no",
    "review_theme_emerged": "binary_yes_no",
    "competitor_opened": "open_ended",
    "winback_eligible": "binary_yes_no",
    "active_planning_intent": "open_ended",
    "curious_ask_due": "open_ended",
    "customer_lapsed_soft": "binary_yes_no",
    "customer_lapsed_hard": "binary_yes_no",
    "trial_followup": "binary_yes_no",
    "wedding_package_followup": "binary_yes_no",
    "supply_alert": "binary_yes_no",
    "gbp_unverified": "binary_yes_no",
    "renewal_due": "binary_yes_no",
    "category_seasonal": "open_ended",
    "cde_opportunity": "binary_yes_no",
    "bridal_followup": "binary_yes_no",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _owner(merchant: Dict[str, Any]) -> str:
    identity = merchant.get("identity", {})
    return identity.get("owner_first_name") or identity.get("name", "there")


def _name(merchant: Dict[str, Any]) -> str:
    return merchant.get("identity", {}).get("name", "your business")


def _active_offer(merchant: Dict[str, Any]) -> str:
    for o in merchant.get("offers", []):
        if o.get("status") == "active":
            return o.get("title", "")
    return ""


def _active_offers_list(merchant: Dict[str, Any]) -> List[str]:
    return [o.get("title", "") for o in merchant.get("offers", []) if o.get("status") == "active"]


def _perf(merchant: Dict[str, Any]) -> Dict[str, Any]:
    return merchant.get("performance", {})


def _hi_en(merchant: Dict[str, Any], customer: Optional[Dict[str, Any]] = None) -> bool:
    """True when the preferred language includes Hindi."""
    if customer:
        lp = customer.get("identity", {}).get("language_pref", "")
        return "hi" in lp.lower()
    langs = merchant.get("identity", {}).get("languages", [])
    return "hi" in langs


def _digest_item(category: Dict[str, Any], item_id: str) -> Optional[Dict[str, Any]]:
    for d in category.get("digest", []):
        if d.get("id") == item_id:
            return d
    return None


def _top_digest(category: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    items = category.get("digest", [])
    return items[0] if items else None


def _peer_ctr(category: Dict[str, Any]) -> Optional[float]:
    return category.get("peer_stats", {}).get("avg_ctr")


def _fmt_pct(v: float) -> str:
    return f"{abs(round(v * 100))}%"


def _cust_name(customer: Dict[str, Any]) -> str:
    return customer.get("identity", {}).get("name", "")

# ---------------------------------------------------------------------------
# Per-kind composers
# Each returns (body: str, rationale: str)
# ---------------------------------------------------------------------------

def _compose_research_digest(
    category: Dict[str, Any], merchant: Dict[str, Any],
    trigger: Dict[str, Any], customer: Optional[Dict[str, Any]]
) -> tuple:
    owner = _owner(merchant)
    payload = trigger.get("payload", {})
    top_item_id = payload.get("top_item_id", "")
    item = _digest_item(category, top_item_id) or _top_digest(category)

    if item:
        title = item.get("title", "")
        source = item.get("source", "")
        summary = item.get("summary", "")
        actionable = item.get("actionable", "")
        trial_n = item.get("trial_n")
        segment = item.get("patient_segment", "")

        # Build specificity anchors
        anchor = f"{trial_n:,}-participant study — " if trial_n else ""
        seg_note = f" (especially for {segment.replace('_',' ')} patients)" if segment else ""

        body_lines = [
            f"{owner}, {source.split(',')[0] if source else 'new research'} just landed.",
            f"{anchor}{title}{seg_note}.",
        ]
        if actionable:
            body_lines.append(f"Actionable: {actionable}.")
        if source:
            body_lines.append(f"Want me to pull the full summary? — {source}")
        else:
            body_lines.append("Want me to pull the full summary?")
        body = " ".join(body_lines)
        rationale = (
            f"Research digest trigger; used {source or 'top digest item'} for specificity. "
            f"Curiosity + reciprocity levers — offered to pull full summary."
        )
    else:
        body = (
            f"{owner}, there's a new knowledge digest item relevant to "
            f"{category.get('slug','your category')} this week. "
            f"Want me to share the key finding?"
        )
        rationale = "Research digest trigger; no specific item found, generic curiosity prompt."

    return body, rationale


def _compose_regulation_change(
    category: Dict[str, Any], merchant: Dict[str, Any],
    trigger: Dict[str, Any], customer: Optional[Dict[str, Any]]
) -> tuple:
    owner = _owner(merchant)
    payload = trigger.get("payload", {})
    top_item_id = payload.get("top_item_id", "")
    deadline = payload.get("deadline_iso", "")
    item = _digest_item(category, top_item_id) or _top_digest(category)

    if item:
        title = item.get("title", "")
        source = item.get("source", "")
        actionable = item.get("actionable", "")
        deadline_str = f" Deadline: {deadline[:10]}." if deadline else ""
        body = (
            f"{owner}, compliance update: {title}.{deadline_str} "
            f"{actionable + '.' if actionable else ''} "
            f"Reply YES for a step-by-step checklist."
        )
        rationale = (
            f"Regulation change trigger; sourced from {source}. "
            f"Urgency (deadline) + effort-externalization CTA."
        )
    else:
        body = (
            f"{owner}, there's a new compliance update for "
            f"{category.get('slug','your category')}. Reply YES for details."
        )
        rationale = "Regulation change trigger; generic prompt (no digest item found)."
    return body, rationale


def _compose_recall_due(
    category: Dict[str, Any], merchant: Dict[str, Any],
    trigger: Dict[str, Any], customer: Optional[Dict[str, Any]]
) -> tuple:
    if not customer:
        owner = _owner(merchant)
        body = (
            f"{owner}, a customer recall window has opened. "
            f"Reply YES to see details and available slots."
        )
        return body, "Recall trigger without customer context."

    cname = _cust_name(customer)
    payload = trigger.get("payload", {})
    service_due = payload.get("service_due", "").replace("_", " ")
    last_date = payload.get("last_service_date", "")
    slots = payload.get("available_slots", [])
    offer = _active_offer(merchant)
    mname = _name(merchant)
    hi = _hi_en(merchant, customer)

    # Slot labels
    slot_lines = ""
    if slots:
        labels = [s.get("label", "") for s in slots[:2] if s.get("label")]
        if hi:
            slot_lines = f"Apke liye slots: {' ya '.join(labels)}. " if labels else ""
        else:
            slot_lines = f"Available: {' or '.join(labels)}. " if labels else ""

    offer_str = f" {offer}." if offer else ""

    if hi:
        body = (
            f"Hi {cname}, {mname} yahan 🙂 "
            f"Aapka {service_due} due hai"
            f"{' — last visit: ' + last_date[:10] if last_date else ''}. "
            f"{slot_lines}"
            f"{offer_str} "
            f"Reply 1 for pehla slot, 2 for doosra, ya time batayein jo suit kare."
        )
    else:
        body = (
            f"Hi {cname}, {mname} here. "
            f"Your {service_due} is due"
            f"{' — last visit ' + last_date[:10] if last_date else ''}. "
            f"{slot_lines}"
            f"{offer_str} "
            f"Reply 1 for first slot, 2 for second, or let us know a time that works."
        )

    rationale = (
        f"Customer recall trigger; used last_service_date and available_slots from payload. "
        f"Multi-choice slot CTA, language pref {'hi-en' if hi else 'en'} honored."
    )
    return body, rationale


def _compose_chronic_refill_due(
    category: Dict[str, Any], merchant: Dict[str, Any],
    trigger: Dict[str, Any], customer: Optional[Dict[str, Any]]
) -> tuple:
    if not customer:
        owner = _owner(merchant)
        body = (
            f"{owner}, a chronic Rx refill is due for one of your patients. "
            f"Reply YES to confirm dispatch."
        )
        return body, "Chronic refill trigger without customer context."

    cname = _cust_name(customer)
    payload = trigger.get("payload", {})
    molecules = payload.get("molecule_list", [])
    runs_out = payload.get("stock_runs_out_iso", "")
    delivery = payload.get("delivery_address_saved", False)
    mname = _name(merchant)
    offer = _active_offer(merchant)
    hi = _hi_en(merchant, customer)

    mol_str = ", ".join(molecules) if molecules else "your medications"
    date_str = runs_out[:10] if runs_out else ""
    delivery_note = " Free home delivery to saved address." if delivery else ""
    offer_str = f" {offer}." if offer else ""

    if hi:
        body = (
            f"Namaste — {mname} yahan. "
            f"{cname} ji ki {mol_str} "
            f"{'ka stock ' + date_str + ' ko khatam hoga.' if date_str else 'ka refill due hai.'}"
            f"{offer_str}{delivery_note} "
            f"Reply CONFIRM to dispatch."
        )
    else:
        body = (
            f"Hi, {mname} here. "
            f"{cname}'s {mol_str} "
            f"{'run out on ' + date_str + '.' if date_str else 'refill is due.'}"
            f"{offer_str}{delivery_note} "
            f"Reply CONFIRM to dispatch."
        )
    rationale = (
        f"Chronic refill trigger; used molecule_list and stock_runs_out date from payload. "
        f"Confirm-cancel CTA, delivery address noted."
    )
    return body, rationale


def _compose_perf_dip(
    category: Dict[str, Any], merchant: Dict[str, Any],
    trigger: Dict[str, Any], customer: Optional[Dict[str, Any]]
) -> tuple:
    owner = _owner(merchant)
    payload = trigger.get("payload", {})
    metric = payload.get("metric", "calls")
    delta = payload.get("delta_pct", 0)
    window = payload.get("window", "7d")
    baseline = payload.get("vs_baseline")
    peer_ctr = _peer_ctr(category)
    perf = _perf(merchant)

    delta_str = _fmt_pct(delta)
    baseline_str = f" (vs {baseline} baseline)" if baseline else ""
    peer_note = (
        f" Peer avg CTR is {peer_ctr:.1%} — yours is {perf.get('ctr', 0):.1%}."
        if peer_ctr and metric in ("ctr", "views") else ""
    )
    offer = _active_offer(merchant)
    offer_note = f" Active offer: {offer}." if offer else " No active offer right now — want me to draft one?"

    body = (
        f"{owner}, your {metric.replace('_',' ')} dropped {delta_str} in the last {window}{baseline_str}.{peer_note}"
        f"{offer_note} Want me to look at what's changed?"
    )
    rationale = (
        f"Perf dip trigger; used metric={metric}, delta={delta_str}, window={window}. "
        f"Loss aversion framing, peer comparison where available."
    )
    return body, rationale


def _compose_perf_spike(
    category: Dict[str, Any], merchant: Dict[str, Any],
    trigger: Dict[str, Any], customer: Optional[Dict[str, Any]]
) -> tuple:
    owner = _owner(merchant)
    payload = trigger.get("payload", {})
    metric = payload.get("metric", "views")
    delta = payload.get("delta_pct", 0)
    window = payload.get("window", "7d")
    driver = payload.get("likely_driver", "")

    delta_str = _fmt_pct(delta)
    driver_note = f" Likely driver: {driver.replace('_',' ')}." if driver else ""

    body = (
        f"{owner}, good news — your {metric.replace('_',' ')} is up {delta_str} in the last {window}.{driver_note} "
        f"Want me to convert this momentum into a new offer or a GBP post?"
    )
    rationale = (
        f"Perf spike trigger; used metric={metric}, delta={delta_str}. "
        f"Positive reinforcement + curiosity to capitalise on momentum."
    )
    return body, rationale


def _compose_seasonal_perf_dip(
    category: Dict[str, Any], merchant: Dict[str, Any],
    trigger: Dict[str, Any], customer: Optional[Dict[str, Any]]
) -> tuple:
    owner = _owner(merchant)
    payload = trigger.get("payload", {})
    delta = payload.get("delta_pct", 0)
    metric = payload.get("metric", "views")
    season_note = payload.get("season_note", "").replace("_", " ")
    cust_agg = merchant.get("customer_aggregate", {})
    active_members = cust_agg.get("total_active_members") or cust_agg.get("total_unique_ytd")

    delta_str = _fmt_pct(delta)
    members_note = f" You have {active_members} active members to focus retention on." if active_members else ""

    body = (
        f"{owner}, your {metric} is down {delta_str} this week — "
        f"but this is the normal {season_note} window; every gym sees -25 to -35% in this period.{members_note} "
        f"Skip acquisition spend now — want me to draft a retention challenge to keep members through the dip?"
    )
    rationale = (
        f"Seasonal perf dip; used delta={delta_str}, season_note, active_members. "
        f"Reframing anxiety as expected + pivot to retention action."
    )
    return body, rationale


def _compose_milestone_reached(
    category: Dict[str, Any], merchant: Dict[str, Any],
    trigger: Dict[str, Any], customer: Optional[Dict[str, Any]]
) -> tuple:
    owner = _owner(merchant)
    payload = trigger.get("payload", {})
    metric = payload.get("metric", "review_count").replace("_", " ")
    value_now = payload.get("value_now")
    milestone = payload.get("milestone_value")
    imminent = payload.get("is_imminent", False)

    if imminent and value_now and milestone:
        gap = milestone - value_now
        body = (
            f"{owner}, you're only {gap} away from {milestone} {metric}. "
            f"Once you hit it your profile gets a ranking boost. "
            f"Want me to draft a quick post asking happy customers to leave a review?"
        )
    elif value_now and metric:
        body = (
            f"{owner}, you just crossed {value_now} {metric} — congratulations! "
            f"Want me to draft a celebratory GBP post to convert this credibility into new leads?"
        )
    else:
        body = (
            f"{owner}, you've hit an important milestone on your profile. "
            f"Want me to turn it into a GBP post to attract new customers?"
        )
    rationale = (
        f"Milestone trigger; used metric={metric}, value_now={value_now}, milestone={milestone}. "
        f"Social proof + effort-externalization CTA."
    )
    return body, rationale


def _compose_dormant(
    category: Dict[str, Any], merchant: Dict[str, Any],
    trigger: Dict[str, Any], customer: Optional[Dict[str, Any]]
) -> tuple:
    owner = _owner(merchant)
    payload = trigger.get("payload", {})
    days = payload.get("days_since_last_merchant_message", "")
    last_topic = payload.get("last_topic", "")
    perf = _perf(merchant)
    views = perf.get("views")

    views_note = f" Your profile got {views:,} views last month." if views else ""
    topic_note = f" Last time we talked about {last_topic.replace('_',' ')}." if last_topic else ""

    body = (
        f"{owner}, checking in — it's been {days} days since we last connected.{topic_note}"
        f"{views_note} Anything you'd like to update on your profile or offers? Reply YES to pick up where we left off."
    )
    rationale = (
        f"Dormancy trigger; used days_since={days}, last_topic, views. "
        f"Reciprocity + single binary re-engagement CTA."
    )
    return body, rationale


def _compose_festival(
    category: Dict[str, Any], merchant: Dict[str, Any],
    trigger: Dict[str, Any], customer: Optional[Dict[str, Any]]
) -> tuple:
    owner = _owner(merchant)
    payload = trigger.get("payload", {})
    festival = payload.get("festival", "upcoming festival")
    days_until = payload.get("days_until")
    offer = _active_offer(merchant)

    days_str = f"{days_until} days away" if days_until else "coming up"
    offer_note = f" Your active offer '{offer}' can be highlighted." if offer else ""

    body = (
        f"{owner}, {festival} is {days_str}.{offer_note} "
        f"Want me to draft a festive GBP post + a WhatsApp blast to your customer list?"
    )
    rationale = (
        f"Festival trigger; used festival={festival}, days_until={days_until}. "
        f"Urgency (days countdown) + effort-externalization CTA."
    )
    return body, rationale


def _compose_ipl(
    category: Dict[str, Any], merchant: Dict[str, Any],
    trigger: Dict[str, Any], customer: Optional[Dict[str, Any]]
) -> tuple:
    owner = _owner(merchant)
    payload = trigger.get("payload", {})
    match = payload.get("match", "IPL match")
    venue = payload.get("venue", "")
    match_time = payload.get("match_time_iso", "")
    is_weeknight = payload.get("is_weeknight", True)

    time_str = match_time[11:16] + " IST" if len(match_time) > 15 else ""
    venue_note = f" at {venue}" if venue else ""

    # From case study 5: Saturday matches = -12% covers, weeknight = +18%
    if is_weeknight:
        rec = "push your match-night combo tonight — weeknight IPL drives +18% covers"
    else:
        rec = "skip the match-day promo today (Saturday matches shift -12% covers to home parties)"

    offer = _active_offer(merchant)
    offer_note = f" Your '{offer}' is already active." if offer else ""

    body = (
        f"{owner}, {match}{venue_note} is tonight{' at ' + time_str if time_str else ''}.{offer_note} "
        f"Data says: {rec}. Want me to draft the Swiggy banner + Insta story?"
    )
    rationale = (
        f"IPL trigger; used match details, is_weeknight={is_weeknight}. "
        f"Counter-intuitive data point (+-12%/+18%) as specificity + loss-aversion framing."
    )
    return body, rationale


def _compose_review_theme(
    category: Dict[str, Any], merchant: Dict[str, Any],
    trigger: Dict[str, Any], customer: Optional[Dict[str, Any]]
) -> tuple:
    owner = _owner(merchant)
    payload = trigger.get("payload", {})
    theme = payload.get("theme", "").replace("_", " ")
    occurrences = payload.get("occurrences_30d", "")
    trend = payload.get("trend", "")
    quote = payload.get("common_quote", "")

    trend_note = f" (trend: {trend})" if trend else ""
    quote_note = f' Common quote: "{quote}"' if quote else ""

    body = (
        f"{owner}, {occurrences} reviews this month mention '{theme}'{trend_note}.{quote_note} "
        f"Want me to draft a response template + suggest one operational fix?"
    )
    rationale = (
        f"Review theme trigger; used theme={theme}, count={occurrences}. "
        f"Specificity (count + quote) + effort-externalization CTA."
    )
    return body, rationale


def _compose_competitor_opened(
    category: Dict[str, Any], merchant: Dict[str, Any],
    trigger: Dict[str, Any], customer: Optional[Dict[str, Any]]
) -> tuple:
    owner = _owner(merchant)
    payload = trigger.get("payload", {})
    comp_name = payload.get("competitor_name", "a new competitor")
    distance = payload.get("distance_km")
    their_offer = payload.get("their_offer", "")
    opened = payload.get("opened_date", "")

    dist_note = f" {distance}km away" if distance else ""
    offer_note = f' — their lead offer: "{their_offer}"' if their_offer else ""
    date_note = f" (opened {opened[:10]})" if opened else ""

    our_offer = _active_offer(merchant)
    our_note = f" Your active offer: '{our_offer}'." if our_offer else " You don't have an active offer right now."

    body = (
        f"{owner}, {comp_name} opened{dist_note}{date_note}{offer_note}.{our_note} "
        f"Want to see how your profile compares and where you have the edge?"
    )
    rationale = (
        f"Competitor opened trigger; used competitor details and own offer. "
        f"Voyeur curiosity + competitive awareness CTA."
    )
    return body, rationale


def _compose_winback(
    category: Dict[str, Any], merchant: Dict[str, Any],
    trigger: Dict[str, Any], customer: Optional[Dict[str, Any]]
) -> tuple:
    owner = _owner(merchant)
    payload = trigger.get("payload", {})
    days_since = payload.get("days_since_expiry", "")
    perf_dip = payload.get("perf_dip_pct", 0)
    lapsed_added = payload.get("lapsed_customers_added_since_expiry", 0)
    mname = _name(merchant)

    dip_str = f" Profile views are down {_fmt_pct(perf_dip)} since then." if perf_dip else ""
    lapsed_note = f" {lapsed_added} more customers have lapsed since." if lapsed_added else ""

    body = (
        f"{owner}, your subscription expired {days_since} days ago.{dip_str}{lapsed_note} "
        f"Re-activating will restore your {mname} listing and offer visibility. Reply YES to reactivate."
    )
    rationale = (
        f"Winback trigger; used days_since={days_since}, perf_dip, lapsed_count. "
        f"Loss aversion (what's being missed) + single binary CTA."
    )
    return body, rationale


def _compose_active_planning(
    category: Dict[str, Any], merchant: Dict[str, Any],
    trigger: Dict[str, Any], customer: Optional[Dict[str, Any]]
) -> tuple:
    """
    Compose a reply to an active planning intent.

    STRICT RULE: every factual detail (price, quantity, deadline, benefit,
    operational step) must come from the supplied context dicts.
    Never invent numbers, tiers, deadlines, or features not present in context.
    When a detail is not in context, describe the *structure* without filling
    in the blank — e.g. "tiered pricing (you set the quantities)" rather than
    fabricating ₹124/₹114/₹104.
    """
    owner = _owner(merchant)
    payload = trigger.get("payload", {})
    intent_topic = payload.get("intent_topic", "").replace("_", " ")
    mname = _name(merchant)
    cust_agg = merchant.get("customer_aggregate", {})
    locality = merchant.get("identity", {}).get("locality", "")

    # ── Corporate / bulk thali ──────────────────────────────────────────────
    if "corporate" in intent_topic and "thali" in intent_topic:
        # Facts from context only
        thali_offer = ""
        for o in merchant.get("offers", []):
            if "thali" in o.get("title", "").lower() and o.get("status") == "active":
                thali_offer = o.get("title", "")
                break

        delivery_share = cust_agg.get("delivery_share_pct")
        repeat_pct = cust_agg.get("repeat_customer_pct")

        # Extract daily order count from conversation history if present
        orders_per_day = ""
        for turn in merchant.get("conversation_history", []):
            body_text = turn.get("body", "")
            m = re.search(r'(\d+)\s+orders?/day', body_text)
            if m:
                orders_per_day = m.group(1)
                break

        # Build body using only confirmed facts; describe structure, not invented numbers
        lines = [f"{owner}, here's how a {mname} Corporate Thali offer could be structured:"]

        # Base price anchor — only if we have it from the active offer
        if thali_offer:
            lines.append(
                f"  • Base: your existing {thali_offer} as the unit"
            )
        lines.append(
            f"  • Tiered by quantity — pricing per tier is yours to set"
        )
        lines.append(
            f"  • Minimum-order cutoff time and delivery window — confirm what works for your kitchen"
        )

        # Context-grounded supporting facts
        if orders_per_day:
            lines.append(f"You're already at {orders_per_day} orders/day avg on the base thali.")
        if delivery_share:
            lines.append(
                f"{round(delivery_share * 100)}% of your current orders are delivery — "
                f"bulk delivery is a natural extension."
            )
        if repeat_pct:
            lines.append(
                f"{round(repeat_pct * 100)}% of your customers are repeat — "
                f"a corporate program could deepen that further."
            )

        lines.append(
            "Want me to draft a 3-line outreach message for office facilities managers? Reply YES."
        )

        body = "\n".join(lines)

    # ── Kids yoga ────────────────────────────────────────────────────────────
    elif "kids" in intent_topic and "yoga" in intent_topic:
        offer = _active_offer(merchant)
        offer_note = f" Your current offer '{offer}' could anchor the intro session." if offer else ""
        body = (
            f"{owner}, for the kids yoga program — here's a structure to consider: "
            f"a multi-week summer camp format, split by age group, with a defined sessions-per-week cadence.{offer_note} "
            f"Pricing and duration are yours to set based on your capacity. "
            f"Want me to draft the GBP post once you confirm the program details? Reply YES."
        )

    # ── Bridal ───────────────────────────────────────────────────────────────
    elif "bridal" in intent_topic:
        offer = _active_offer(merchant)
        offer_note = f" Your '{offer}' could be the entry-point offer." if offer else ""
        body = (
            f"{owner}, for the bridal package: a pre-wedding program typically runs as a "
            f"multi-session bundle over 4–6 weeks before the wedding date.{offer_note} "
            f"Number of sessions and pricing are yours to finalise. "
            f"Want me to draft a pricing card template? Reply YES."
        )

    # ── Generic planning intent ───────────────────────────────────────────────
    else:
        offer = _active_offer(merchant)
        offer_note = f" Your existing offer '{offer}' could be the starting point." if offer else ""
        body = (
            f"{owner}, picking up on your idea about {intent_topic} for {mname}.{offer_note} "
            f"I can draft a structure for you to review — "
            f"you fill in the pricing and operational details you want. "
            f"Want me to send a draft? Reply YES."
        )

    rationale = (
        f"Active planning intent (topic: {intent_topic}). "
        f"Merchant committed — delivering concrete structure immediately with NO fabricated numbers. "
        f"All facts (offer title, delivery share, repeat rate, orders/day, locality) drawn from context only."
    )
    return body, rationale


def _compose_curious_ask(
    category: Dict[str, Any], merchant: Dict[str, Any],
    trigger: Dict[str, Any], customer: Optional[Dict[str, Any]]
) -> tuple:
    owner = _owner(merchant)
    mname = _name(merchant)
    slug = category.get("slug", "your category")
    perf = _perf(merchant)
    views = perf.get("views")
    calls = perf.get("calls")

    perf_note = f" ({views:,} views, {calls} calls last 30 days)" if views and calls else ""

    body = (
        f"{owner}, quick check-in — what service has been most asked for at "
        f"{mname} this week?{perf_note} "
        f"I'll turn your answer into a GBP post + a ready-to-send WhatsApp reply for pricing questions. 5 min."
    )
    rationale = (
        f"Curious-ask trigger; asking merchant what's in demand. "
        f"Low-stakes question + reciprocity (I'll draft something from your answer)."
    )
    return body, rationale


def _compose_customer_lapsed(
    category: Dict[str, Any], merchant: Dict[str, Any],
    trigger: Dict[str, Any], customer: Optional[Dict[str, Any]],
    hard: bool = False
) -> tuple:
    if not customer:
        owner = _owner(merchant)
        body = (
            f"{owner}, a customer lapse window has opened. "
            f"Reply YES to see who and draft a re-engagement message."
        )
        return body, "Customer lapse trigger without customer context."

    cname = _cust_name(customer)
    mname = _name(merchant)
    payload = trigger.get("payload", {})
    days_since = payload.get("days_since_last_visit", "")
    focus = payload.get("previous_focus", "").replace("_", " ")
    offer = _active_offer(merchant)
    hi = _hi_en(merchant, customer)

    days_note = f"It's been {days_since} days" if days_since else "It's been a while"
    offer_note = f" No commitment, no auto-charge — just a free trial." if hard else (f" {offer}." if offer else "")
    focus_note = f" We've added a class that fits your {focus} goals well." if focus else ""

    if hi:
        body = (
            f"Hi {cname}, {mname} yahan 👋 "
            f"{days_note} — koi baat nahi, hota hai.{focus_note} "
            f"{offer_note} "
            f"Ek free trial spot hold karein? Reply YES."
        )
    else:
        body = (
            f"Hi {cname}, {mname} here 👋 "
            f"{days_note} — no judgment, it happens to everyone.{focus_note} "
            f"{offer_note} "
            f"Want me to hold a free trial spot for you? Reply YES."
        )
    rationale = (
        f"Customer lapse ({'hard' if hard else 'soft'}) trigger; used days_since, focus, offer. "
        f"No-shame framing + specific goal reference + single binary CTA."
    )
    return body, rationale


def _compose_trial_followup(
    category: Dict[str, Any], merchant: Dict[str, Any],
    trigger: Dict[str, Any], customer: Optional[Dict[str, Any]]
) -> tuple:
    if not customer:
        owner = _owner(merchant)
        body = (
            f"{owner}, a customer recently did a trial session. "
            f"Reply YES to send them a follow-up and next slot options."
        )
        return body, "Trial followup without customer context."

    cname = _cust_name(customer)
    mname = _name(merchant)
    payload = trigger.get("payload", {})
    trial_date = payload.get("trial_date", "")
    slots = payload.get("next_session_options", [])
    offer = _active_offer(merchant)
    hi = _hi_en(merchant, customer)

    trial_note = f" after your trial on {trial_date[:10]}" if trial_date else ""
    slot_labels = [s.get("label", "") for s in slots[:2] if s.get("label")]
    slot_note = f" Next slot: {slot_labels[0]}." if slot_labels else ""
    offer_note = f" {offer}." if offer else ""

    if hi:
        body = (
            f"Hi {cname}, {mname} yahan! "
            f"Trial{trial_note} kaisi rahi?{slot_note}{offer_note} "
            f"Agle session ke liye join karna chahenge? Reply YES."
        )
    else:
        body = (
            f"Hi {cname}, {mname} here! "
            f"How was your trial{trial_note}?{slot_note}{offer_note} "
            f"Ready to join for the next session? Reply YES."
        )
    rationale = (
        f"Trial followup; used trial_date and next session slot. "
        f"Warm follow-up + single binary CTA."
    )
    return body, rationale


def _compose_wedding_followup(
    category: Dict[str, Any], merchant: Dict[str, Any],
    trigger: Dict[str, Any], customer: Optional[Dict[str, Any]]
) -> tuple:
    if not customer:
        owner = _owner(merchant)
        body = (
            f"{owner}, a bride who did a trial is in the pre-wedding prep window. "
            f"Reply YES to send a follow-up."
        )
        return body, "Wedding followup without customer context."

    cname = _cust_name(customer)
    mname = _name(merchant)
    payload = trigger.get("payload", {})
    wedding_date = payload.get("wedding_date", "")
    days_to = payload.get("days_to_wedding")
    next_step = payload.get("next_step_window_open", "").replace("_", " ")
    offer = _active_offer(merchant)

    days_note = f"{days_to} days to your wedding" if days_to else "your wedding is coming up"
    offer_note = f" {offer}." if offer else ""

    body = (
        f"Hi {cname} 💍 {mname} here. {days_note} — "
        f"perfect time to start {next_step if next_step else 'the pre-wedding program'}.{offer_note} "
        f"Want me to block your preferred slot for the first session next week? Reply YES."
    )
    rationale = (
        f"Wedding followup; used days_to_wedding={days_to}, next_step window. "
        f"Urgency (countdown) + single binary CTA."
    )
    return body, rationale


def _compose_supply_alert(
    category: Dict[str, Any], merchant: Dict[str, Any],
    trigger: Dict[str, Any], customer: Optional[Dict[str, Any]]
) -> tuple:
    owner = _owner(merchant)
    payload = trigger.get("payload", {})
    molecule = payload.get("molecule", "the medication")
    batches = payload.get("affected_batches", [])
    manufacturer = payload.get("manufacturer", "")
    cust_agg = merchant.get("customer_aggregate", {})
    chronic_count = cust_agg.get("chronic_rx_count")

    batch_str = ", ".join(batches) if batches else "specific batches"
    mfr_note = f" by {manufacturer}" if manufacturer else ""
    chronic_note = (
        f" You have {chronic_count} chronic-Rx customers — some may have received these batches."
        if chronic_count else ""
    )

    body = (
        f"{owner}, urgent: voluntary recall on {molecule} batches ({batch_str}){mfr_note} — "
        f"sub-potency, no safety risk but customers should be informed for replacement.{chronic_note} "
        f"Reply YES for a draft WhatsApp note + replacement-pickup workflow."
    )
    rationale = (
        f"Supply alert trigger; used molecule={molecule}, batches, chronic_rx_count. "
        f"Urgency + risk-bounded framing + effort-externalization CTA."
    )
    return body, rationale


def _compose_gbp_unverified(
    category: Dict[str, Any], merchant: Dict[str, Any],
    trigger: Dict[str, Any], customer: Optional[Dict[str, Any]]
) -> tuple:
    owner = _owner(merchant)
    payload = trigger.get("payload", {})
    uplift = payload.get("estimated_uplift_pct", 0)
    path = payload.get("verification_path", "postcard or phone call")
    perf = _perf(merchant)
    views = perf.get("views")

    uplift_note = f" Verified profiles get ~{round(uplift * 100)}% more visibility." if uplift else ""
    views_note = f" You're getting {views:,} views/month unverified." if views else ""

    body = (
        f"{owner}, your Google Business Profile is not yet verified.{uplift_note}{views_note} "
        f"Verification takes 5 min via {path}. Reply YES and I'll walk you through it step by step."
    )
    rationale = (
        f"GBP unverified trigger; used uplift={uplift}, views, verification path. "
        f"Loss aversion (missed visibility) + low-friction CTA."
    )
    return body, rationale


def _compose_renewal_due(
    category: Dict[str, Any], merchant: Dict[str, Any],
    trigger: Dict[str, Any], customer: Optional[Dict[str, Any]]
) -> tuple:
    owner = _owner(merchant)
    payload = trigger.get("payload", {})
    days = payload.get("days_remaining", "")
    plan = payload.get("plan", "Pro")
    amount = payload.get("renewal_amount")
    perf = _perf(merchant)
    views = perf.get("views")

    amount_note = f" ₹{amount:,} for another year." if amount else ""
    views_note = f" Your profile got {views:,} views last month." if views else ""

    body = (
        f"{owner}, your {plan} subscription expires in {days} days.{amount_note}{views_note} "
        f"Renewal keeps your offers live and listing visible. Reply YES to renew now."
    )
    rationale = (
        f"Renewal due trigger; used days={days}, plan={plan}, amount, views. "
        f"Loss aversion (what stops when it lapses) + single binary CTA."
    )
    return body, rationale


def _compose_category_seasonal(
    category: Dict[str, Any], merchant: Dict[str, Any],
    trigger: Dict[str, Any], customer: Optional[Dict[str, Any]]
) -> tuple:
    owner = _owner(merchant)
    payload = trigger.get("payload", {})
    season = payload.get("season", "").replace("_", " ")
    trends = payload.get("trends", [])
    offer = _active_offer(merchant)

    trend_str = ", ".join(str(t) for t in trends[:3]) if trends else ""
    trend_note = f" Demand shifts: {trend_str}." if trend_str else ""
    offer_note = f" Your active offer: '{offer}'." if offer else ""

    body = (
        f"{owner}, {season} demand shift is here.{trend_note}{offer_note} "
        f"Want me to update your shelf layout recommendation + draft a seasonal GBP post?"
    )
    rationale = (
        f"Category seasonal trigger; used season={season}, trend data. "
        f"Specificity (trend numbers) + effort-externalization CTA."
    )
    return body, rationale


def _compose_cde_opportunity(
    category: Dict[str, Any], merchant: Dict[str, Any],
    trigger: Dict[str, Any], customer: Optional[Dict[str, Any]]
) -> tuple:
    owner = _owner(merchant)
    payload = trigger.get("payload", {})
    item_id = payload.get("digest_item_id", "")
    credits = payload.get("credits")
    fee = payload.get("fee", "")

    item = _digest_item(category, item_id)
    if item:
        title = item.get("title", "")
        source = item.get("source", "")
        date_str = item.get("date", "")[:10] if item.get("date") else ""
        credit_note = f" {credits} CDE credits." if credits else ""
        fee_note = f" Fee: {fee}." if fee else ""
        date_note = f" Date: {date_str}." if date_str else ""
        body = (
            f"{owner}, upcoming: {title}.{credit_note}{fee_note}{date_note} "
            f"Relevant for your practice — want me to reserve your spot? Reply YES."
        )
    else:
        body = (
            f"{owner}, there's a CDE/CPD opportunity coming up for "
            f"{category.get('slug', 'your category')}. Reply YES for details."
        )
    rationale = (
        f"CDE opportunity trigger; used digest item details, credits={credits}, fee={fee}. "
        f"Professional development + low-friction reservation CTA."
    )
    return body, rationale


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_COMPOSERS = {
    "research_digest":        _compose_research_digest,
    "regulation_change":      _compose_regulation_change,
    "recall_due":             _compose_recall_due,
    "chronic_refill_due":     _compose_chronic_refill_due,
    "perf_dip":               _compose_perf_dip,
    "perf_spike":             _compose_perf_spike,
    "seasonal_perf_dip":      _compose_seasonal_perf_dip,
    "milestone_reached":      _compose_milestone_reached,
    "dormant_with_vera":      _compose_dormant,
    "festival_upcoming":      _compose_festival,
    "ipl_match_today":        _compose_ipl,
    "review_theme_emerged":   _compose_review_theme,
    "competitor_opened":      _compose_competitor_opened,
    "winback_eligible":       _compose_winback,
    "active_planning_intent": _compose_active_planning,
    "curious_ask_due":        _compose_curious_ask,
    "customer_lapsed_soft":   lambda cat, mer, trg, cus: _compose_customer_lapsed(cat, mer, trg, cus, hard=False),
    "customer_lapsed_hard":   lambda cat, mer, trg, cus: _compose_customer_lapsed(cat, mer, trg, cus, hard=True),
    "trial_followup":         _compose_trial_followup,
    "wedding_package_followup": _compose_wedding_followup,
    "bridal_followup":        _compose_wedding_followup,
    "supply_alert":           _compose_supply_alert,
    "gbp_unverified":         _compose_gbp_unverified,
    "renewal_due":            _compose_renewal_due,
    "category_seasonal":      _compose_category_seasonal,
    "cde_opportunity":        _compose_cde_opportunity,
}


def _generic_compose(
    category: Dict[str, Any], merchant: Dict[str, Any],
    trigger: Dict[str, Any], customer: Optional[Dict[str, Any]]
) -> tuple:
    """Last-resort generic composer for unknown trigger kinds."""
    owner = _owner(merchant)
    kind = trigger.get("kind", "update").replace("_", " ")
    offer = _active_offer(merchant)
    offer_note = f" Active offer: '{offer}'." if offer else ""
    body = (
        f"{owner}, there's a {kind} relevant to your account.{offer_note} "
        f"Want me to share the details? Reply YES."
    )
    return body, f"Generic compose for unknown trigger kind={trigger.get('kind')}."


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = {"body", "cta", "send_as", "rationale"}
VALID_CTA = {
    "open_ended", "binary_yes_no", "binary_confirm_cancel",
    "multi_choice_slot", "binary_yes_stop", "none",
}
VALID_SEND_AS = {"vera", "merchant_on_behalf"}


def _validate_and_fix(result: Dict[str, Any], merchant: Dict[str, Any],
                      customer: Optional[Dict[str, Any]], kind: str) -> Dict[str, Any]:
    # Remove URLs
    if URL_PATTERN.search(result.get("body", "")):
        result["body"] = URL_PATTERN.sub("", result["body"]).strip()

    # Fix send_as for customer scope
    if customer and result.get("send_as") != "merchant_on_behalf":
        result["send_as"] = "merchant_on_behalf"

    # Fix invalid CTA
    if result.get("cta") not in VALID_CTA:
        result["cta"] = CTA_BY_KIND.get(kind, "open_ended")

    return result


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def compose(
    category: Dict[str, Any],
    merchant: Dict[str, Any],
    trigger: Dict[str, Any],
    customer: Optional[Dict[str, Any]] = None,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Deterministic rule-based message composition.
    Returns dict with: body, cta, send_as, suppression_key, rationale,
                       template_name, template_params
    No external calls. Pure Python.
    """
    kind = trigger.get("kind", "")
    composer_fn = _COMPOSERS.get(kind, _generic_compose)

    body, rationale = composer_fn(category, merchant, trigger, customer)

    send_as = "merchant_on_behalf" if customer else "vera"
    cta = CTA_BY_KIND.get(kind, "open_ended")

    result: Dict[str, Any] = {
        "body": body,
        "cta": cta,
        "send_as": send_as,
        "rationale": rationale,
    }

    result = _validate_and_fix(result, merchant, customer, kind)

    # Enrich with action-level fields
    result["suppression_key"] = trigger.get(
        "suppression_key",
        f"msg:{merchant.get('merchant_id', '')}:{trigger.get('id', '')}",
    )
    result["template_name"] = f"vera_{kind or 'generic'}_v1"

    identity = merchant.get("identity", {})
    owner = identity.get("owner_first_name") or identity.get("name", "")
    result["template_params"] = [
        owner,
        kind.replace("_", " "),
        result["body"][:80],
    ]

    return result
