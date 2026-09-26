"""
End-to-end test for all 30 canonical test pairs.

For each pair:
  1. POST /v1/context  — category, merchant, customer (if any), trigger
  2. POST /v1/tick     — with the pair's trigger_id
  3. Validate the returned action on 10+ criteria

Usage:
    .venv/bin/python test_all_pairs.py
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Config ──────────────────────────────────────────────────────────────────
BOT_URL   = "http://localhost:8080"
DATA_ROOT = Path(__file__).parent.parent / "magicpin-ai-challenge" / "dataset" / "expanded"

URL_RE       = re.compile(r'https?://\S+|www\.\S+', re.IGNORECASE)
FALLBACK_RE  = re.compile(
    r'LLM unavailable|quick update on your account|there\'s a \w+ that may be relevant',
    re.IGNORECASE,
)
VALID_CTA    = {
    "open_ended", "binary_yes_no", "binary_confirm_cancel",
    "multi_choice_slot", "binary_yes_stop", "none",
}
VALID_SEND_AS = {"vera", "merchant_on_behalf"}
REQUIRED_ACTION_FIELDS = {
    "conversation_id", "merchant_id", "send_as", "trigger_id",
    "template_name", "body", "cta", "suppression_key", "rationale",
}

# ── HTTP helpers ────────────────────────────────────────────────────────────

def _post(path: str, payload: Dict) -> Tuple[Optional[Dict], Optional[str]]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        BOT_URL + path, data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
        except Exception:
            body = {}
        return body, f"HTTP {e.code}"
    except Exception as exc:
        return None, str(exc)


def _get(path: str) -> Tuple[Optional[Dict], Optional[str]]:
    try:
        with urllib.request.urlopen(BOT_URL + path, timeout=10) as r:
            return json.loads(r.read()), None
    except Exception as exc:
        return None, str(exc)


# ── Context loaders ─────────────────────────────────────────────────────────

_ctx_version: Dict[Tuple[str, str], int] = {}   # track versions sent so far


def _push(scope: str, context_id: str, payload: Dict) -> Optional[str]:
    """Push a context, bumping the version on re-push to avoid stale_version rejection."""
    key = (scope, context_id)
    _ctx_version[key] = _ctx_version.get(key, 0) + 1
    resp, err = _post("/v1/context", {
        "scope": scope,
        "context_id": context_id,
        "version": _ctx_version[key],
        "payload": payload,
        "delivered_at": "2026-04-26T10:00:00Z",
    })
    if err and "stale_version" not in str(resp):
        return f"context push failed ({scope}/{context_id}): {err}"
    if resp and not resp.get("accepted") and resp.get("reason") != "stale_version":
        return f"context rejected ({scope}/{context_id}): {resp}"
    return None


def _load_json(path: Path) -> Optional[Dict]:
    if not path.exists():
        return None
    return json.loads(path.read_text())


def load_and_push_contexts(pair: Dict) -> List[str]:
    """Load category/merchant/customer/trigger and push to the bot. Returns list of errors."""
    errors: List[str] = []

    trigger_id  = pair["trigger_id"]
    merchant_id = pair["merchant_id"]
    customer_id = pair.get("customer_id")

    # Load trigger
    trg_path = DATA_ROOT / "triggers" / f"{trigger_id}.json"
    trigger = _load_json(trg_path)
    if not trigger:
        errors.append(f"trigger file missing: {trg_path.name}")
        return errors

    # Load merchant
    mer_path = DATA_ROOT / "merchants" / f"{merchant_id}.json"
    merchant = _load_json(mer_path)
    if not merchant:
        errors.append(f"merchant file missing: {mer_path.name}")
        return errors

    # Load category
    cat_slug = merchant.get("category_slug", "")
    cat_path = DATA_ROOT / "categories" / f"{cat_slug}.json"
    category = _load_json(cat_path)
    if not category:
        errors.append(f"category file missing: {cat_path.name}")
        return errors

    # Push category
    err = _push("category", cat_slug, category)
    if err:
        errors.append(err)

    # Push merchant
    err = _push("merchant", merchant_id, merchant)
    if err:
        errors.append(err)

    # Push customer (optional)
    if customer_id:
        cust_path = DATA_ROOT / "customers" / f"{customer_id}.json"
        customer = _load_json(cust_path)
        if not customer:
            errors.append(f"customer file missing: {cust_path.name}")
        else:
            err = _push("customer", customer_id, customer)
            if err:
                errors.append(err)

    # Push trigger
    err = _push("trigger", trigger_id, trigger)
    if err:
        errors.append(err)

    return errors


# ── Tick + validate ──────────────────────────────────────────────────────────

def call_tick(trigger_id: str) -> Tuple[Optional[Dict], Optional[str]]:
    return _post("/v1/tick", {
        "now": "2026-04-26T10:35:00Z",
        "available_triggers": [trigger_id],
    })


def validate_action(action: Dict, pair: Dict) -> List[str]:
    """Return list of failure reasons. Empty = PASS."""
    failures: List[str] = []

    # Required fields
    missing = REQUIRED_ACTION_FIELDS - set(action.keys())
    if missing:
        failures.append(f"missing fields: {sorted(missing)}")

    body = action.get("body", "")

    # Non-empty body
    if not body or len(body.strip()) < 15:
        failures.append(f"body too short: {body!r}")

    # No URL
    if URL_RE.search(body):
        failures.append(f"body contains URL")

    # No fallback/generic wording
    if FALLBACK_RE.search(body):
        failures.append(f"body contains fallback/generic wording: {body[:80]!r}")

    # Valid CTA
    cta = action.get("cta", "")
    if cta not in VALID_CTA:
        failures.append(f"invalid cta: {cta!r}")

    # Valid send_as
    send_as = action.get("send_as", "")
    if send_as not in VALID_SEND_AS:
        failures.append(f"invalid send_as: {send_as!r}")

    # Customer scope → merchant_on_behalf
    if pair.get("customer_id") and send_as != "merchant_on_behalf":
        failures.append(f"customer-scoped trigger must have send_as=merchant_on_behalf, got {send_as!r}")

    # Correct merchant_id
    if action.get("merchant_id") != pair["merchant_id"]:
        failures.append(
            f"merchant_id mismatch: expected {pair['merchant_id']!r}, got {action.get('merchant_id')!r}"
        )

    # Correct trigger_id
    if action.get("trigger_id") != pair["trigger_id"]:
        failures.append(
            f"trigger_id mismatch: expected {pair['trigger_id']!r}, got {action.get('trigger_id')!r}"
        )

    # customer_id matches pair
    expected_cid = pair.get("customer_id")
    if expected_cid and action.get("customer_id") != expected_cid:
        failures.append(
            f"customer_id mismatch: expected {expected_cid!r}, got {action.get('customer_id')!r}"
        )

    # suppression_key present and non-empty
    if not action.get("suppression_key"):
        failures.append("suppression_key missing or empty")

    # rationale present and non-empty
    if not action.get("rationale"):
        failures.append("rationale missing or empty")

    return failures


# ── Main ────────────────────────────────────────────────────────────────────

def run_all() -> None:
    # Verify server is up
    health, err = _get("/v1/healthz")
    if err or not health or health.get("status") != "ok":
        print(f"FATAL: server not reachable — {err or health}")
        sys.exit(1)
    print(f"Server up. uptime={health.get('uptime_seconds')}s")

    # Wipe all in-memory state so no suppression keys or conversations bleed
    # between the manual tests done earlier and this automated run.
    _post("/v1/teardown", {})
    print("State wiped via /v1/teardown.\n")

    # Reset our local version tracker too
    _ctx_version.clear()

    pairs_path = DATA_ROOT / ".." / "test_pairs.json"
    # test_pairs.json lives directly under expanded/
    pairs_path = DATA_ROOT / "test_pairs.json"
    # Actually the generator writes it to the out_dir directly:
    pairs_data = json.loads(pairs_path.read_text())
    pairs: List[Dict] = pairs_data["pairs"]

    results: List[Tuple[str, bool, List[str]]] = []

    for pair in pairs:
        tid = pair["test_id"]

        # 1. Push all contexts
        ctx_errors = load_and_push_contexts(pair)
        if ctx_errors:
            results.append((tid, False, [f"context load error: {'; '.join(ctx_errors)}"]))
            continue

        # 2. Small pause so state is settled
        time.sleep(0.05)

        # 3. Call tick
        resp, err = call_tick(pair["trigger_id"])
        if err:
            results.append((tid, False, [f"tick HTTP error: {err}; resp={resp}"]))
            continue
        if resp is None:
            results.append((tid, False, ["tick returned None"]))
            continue

        actions = resp.get("actions", [])

        # The action for this specific trigger might be suppressed if a prior
        # test pair pushed the same trigger (shouldn't happen since all 30 have
        # distinct trigger_ids, but guard anyway).
        if not actions:
            results.append((tid, False, ["tick returned empty actions (trigger suppressed or context missing)"]))
            continue

        # Find the action for our trigger_id
        action = next(
            (a for a in actions if a.get("trigger_id") == pair["trigger_id"]),
            actions[0],   # fallback to first if only one action
        )

        # 4. Validate
        failures = validate_action(action, pair)
        results.append((tid, len(failures) == 0, failures))

    # ── Report ───────────────────────────────────────────────────────────────
    print(f"{'Test':<6}  {'Result':<6}  Details")
    print("-" * 72)
    passes = 0
    for tid, ok, reasons in results:
        status = "PASS" if ok else "FAIL"
        detail = "" if ok else "  ← " + " | ".join(reasons)
        print(f"{tid:<6}  {status:<6}{detail}")
        if ok:
            passes += 1

    print("-" * 72)
    print(f"\n{passes}/{len(results)} PASSED\n")

    if passes < len(results):
        sys.exit(1)


if __name__ == "__main__":
    run_all()
