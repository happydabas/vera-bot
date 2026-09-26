"""
Quick local test for T01 — runs compose() directly without needing a running server.
Usage: python test_t01.py
"""
import json
import sys
import os

# Make sure we can import from the vera-bot directory
sys.path.insert(0, os.path.dirname(__file__))

from composer import compose

# ── T01 exact context ──────────────────────────────────────────────────────

CATEGORY = {
    "slug": "restaurants",
    "display_name": "Restaurants & Cafes",
    "voice": {
        "tone": "warm_busy_practical",
        "register": "fellow_operator",
        "code_mix": "hindi_english_natural",
        "vocab_allowed": ["footfall", "covers", "AOV", "RPC", "table turnover", "thali", "biryani"],
        "vocab_taboo": ["best food in city", "guaranteed packed house", "viral guarantee"],
        "salutation_examples": ["Hi {chef_or_owner_first_name}"],
    },
    "offer_catalog": [
        {"id": "res_003", "title": "Weekday Lunch Thali @ ₹149", "value": "149",
         "audience": "new_user", "type": "service_at_price"},
    ],
    "peer_stats": {
        "scope": "metro_casual_dining_2026",
        "avg_rating": 4.2, "avg_review_count": 142,
        "avg_views_30d": 4800, "avg_calls_30d": 38,
        "avg_directions_30d": 95, "avg_ctr": 0.025,
    },
    "digest": [
        {
            "id": "d_2026W17_ipl_window",
            "kind": "seasonal",
            "title": "IPL home-match Saturdays underperformed weeknight matches",
            "source": "magicpin order data, Apr 2026",
            "summary": "Saturday IPL matches shift orders to home-watch parties; covers -12%. Weeknight +18%.",
            "actionable": "Push match-night combos on Tue/Wed/Thu only",
        }
    ],
    "seasonal_beats": [
        {"month_range": "Mar-Apr", "note": "IPL season"}
    ],
    "trend_signals": [
        {"query": "weekday lunch thali", "delta_yoy": 0.34, "segment_age": "office_25-45"}
    ],
}

MERCHANT = {
    "merchant_id": "m_006_southindiancafe_restaurant_bangalore",
    "category_slug": "restaurants",
    "identity": {
        "name": "Mylari South Indian Cafe",
        "city": "Bangalore",
        "locality": "Indiranagar",
        "place_id": "ChIJ_INDIRANAGAR_RESTAURANT_006",
        "verified": True,
        "languages": ["en", "hi", "kn"],
        "owner_first_name": "Suresh",
        "established_year": 2014,
    },
    "subscription": {"status": "active", "plan": "Pro", "days_remaining": 240},
    "performance": {
        "window_days": 30,
        "views": 12400, "calls": 88, "directions": 320,
        "ctr": 0.032, "leads": 145,
        "delta_7d": {"views_pct": 0.05, "calls_pct": 0.02},
    },
    "offers": [
        {"id": "o_mylari_001", "title": "Weekday Lunch Thali @ ₹149",
         "status": "active", "started": "2026-01-10"},
    ],
    "conversation_history": [
        {
            "ts": "2026-04-25T11:00:00Z",
            "from": "vera",
            "body": "Your weekday thali is doing well — 18 orders/day avg. Want me to add a corporate-bulk version?",
            "engagement": "merchant_replied",
        },
        {
            "ts": "2026-04-25T11:30:00Z",
            "from": "merchant",
            "body": "Yes good idea, what would it look like",
            "engagement": "intent_question",
        },
    ],
    "customer_aggregate": {
        "total_unique_ytd": 4200,
        "repeat_customer_pct": 0.42,
        "delivery_share_pct": 0.45,
    },
    "signals": ["high_volume", "stable_growth", "engaged_in_last_24h"],
    "review_themes": [
        {"theme": "thali_quality", "sentiment": "pos", "occurrences_30d": 22},
    ],
}

TRIGGER = {
    "id": "trg_013_corporate_thali_planning",
    "scope": "merchant",
    "kind": "active_planning_intent",
    "source": "internal",
    "merchant_id": "m_006_southindiancafe_restaurant_bangalore",
    "customer_id": None,
    "payload": {
        "intent_topic": "corporate_bulk_thali_package",
        "merchant_last_message": "Yes good idea, what would it look like",
    },
    "urgency": 4,
    "suppression_key": "planning:m_006:corp_thali:2026-W17",
    "expires_at": "2026-04-29T00:00:00Z",
}

# ── Run ────────────────────────────────────────────────────────────────────

result = compose(CATEGORY, MERCHANT, TRIGGER, customer=None)

print("\n" + "="*60)
print("T01 — active_planning_intent / corporate thali")
print("="*60)
print(f"\nbody:\n{result['body']}")
print(f"\ncta:            {result['cta']}")
print(f"send_as:        {result['send_as']}")
print(f"suppression_key:{result['suppression_key']}")
print(f"template_name:  {result['template_name']}")
print(f"\nrationale:\n{result['rationale']}")

# Validation checks
print("\n" + "-"*60)
print("VALIDATION")
print("-"*60)

import re
URL_RE = re.compile(r'https?://\S+|www\.\S+', re.IGNORECASE)
body = result['body']

checks = [
    ("has body",              bool(body.strip())),
    ("no URL",                not URL_RE.search(body)),
    ("has suppression_key",   bool(result.get("suppression_key"))),
    ("has rationale",         bool(result.get("rationale"))),
    ("valid send_as",         result.get("send_as") in ("vera", "merchant_on_behalf")),
    ("valid cta",             result.get("cta") in
                              ("open_ended","binary_yes_no","binary_confirm_cancel",
                               "multi_choice_slot","binary_yes_stop","none")),
    ("mentions owner Suresh", "Suresh" in body),
    ("no LLM unavailable msg",  "LLM unavailable" not in body),
    ("mentions thali/price",  "thali" in body.lower() or "₹" in body),
    ("mentions Indiranagar or locality", "Indiranagar" in body or "Mylari" in body),
]

all_pass = True
for label, ok in checks:
    status = "PASS" if ok else "FAIL"
    if not ok:
        all_pass = False
    print(f"  [{status}] {label}")

print("-"*60)
print(f"  Overall: {'ALL PASS' if all_pass else 'SOME FAILURES'}")
print("="*60 + "\n")

sys.exit(0 if all_pass else 1)
