"""Mandate compiler: natural language → structured, schema-validated Guardrails.

Gemini does the heavy lifting; a regex/heuristic compiler is the fallback and
is also what the unit tests exercise. Whatever the compiler returns is clamped
to the hard ceilings (UPI Circle full-delegation limits) so a user can never
write a mandate that out-authorises the rail.
"""

from __future__ import annotations

import re

from .config import settings
from .gemini import generate_json
from .models import Guardrails

_SYSTEM = """You compile a user's natural-language payment mandate for an AI agent into a strict JSON policy.
Be conservative: if the user does not explicitly allow something, do not allow it.
Amounts are INR. Interpret 'k' as thousand. If the user names merchants, list them exactly as written (lowercase).
If the user says 'never a new payee', 'only these', 'no new merchants' → allow_new_payees=false.
Categories are short lowercase nouns (groceries, food delivery, transport, subscriptions, utilities, pharmacy, shopping).
If no period cap is stated, set period_cap = 3 x per_txn_cap and period = 'month'.
Return ONLY JSON matching the schema."""

_SCHEMA = {
    "type": "object",
    "properties": {
        "per_txn_cap": {"type": "number"},
        "period_cap": {"type": "number"},
        "period": {"type": "string", "enum": ["day", "week", "month"]},
        "allowed_merchants": {"type": "array", "items": {"type": "string"}},
        "allow_new_payees": {"type": "boolean"},
        "categories": {"type": "array", "items": {"type": "string"}},
        "blocked_categories": {"type": "array", "items": {"type": "string"}},
        "requires_refundability": {"type": "boolean"},
        "max_txns_per_day": {"type": "integer"},
        "step_up_above": {"type": "number"},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["per_txn_cap", "period_cap", "period", "allowed_merchants", "allow_new_payees", "categories"],
}

_KNOWN_MERCHANTS = [
    "bigbasket", "zepto", "blinkit", "swiggy", "zomato", "instamart", "amazon", "flipkart",
    "uber", "ola", "rapido", "netflix", "spotify", "hotstar", "jiomart", "dmart", "1mg", "pharmeasy",
    "apollo", "bescom", "airtel", "jio", "myntra", "nykaa", "dunzo", "irctc", "redbus",
]
_CATEGORY_HINTS = {
    "groceries": ["grocer", "vegetable", "milk", "kirana", "bigbasket", "zepto", "blinkit", "instamart", "jiomart", "dmart"],
    "food delivery": ["food", "swiggy", "zomato", "lunch", "dinner", "meal"],
    "transport": ["cab", "uber", "ola", "rapido", "auto", "commute", "ride", "metro"],
    "subscriptions": ["subscription", "netflix", "spotify", "hotstar", "renewal"],
    "utilities": ["electricity", "bescom", "bill", "broadband", "airtel", "jio", "recharge", "gas"],
    "pharmacy": ["medicine", "pharmacy", "1mg", "pharmeasy", "apollo"],
    "shopping": ["amazon", "flipkart", "myntra", "nykaa", "shopping"],
}


def _amount(tok: str) -> float:
    tok = tok.replace(",", "").lower().replace("₹", "").replace("rs", "").replace("inr", "").strip()
    mult = 1.0
    if tok.endswith("k"):
        mult, tok = 1000.0, tok[:-1]
    return float(tok) * mult


def heuristic_compile(text: str) -> tuple[Guardrails, list[str]]:
    t = text.lower()
    notes: list[str] = ["compiled with heuristic fallback (Gemini unavailable)"]
    amounts = [(_amount(m.group(1)), m.start()) for m in re.finditer(r"(?:₹|rs\.?|inr)?\s*(\d[\d,]*(?:\.\d+)?k?)\b", t)]
    amounts = [(a, p) for a, p in amounts if a >= 50]

    per_txn = None
    period_cap = None
    period = "month"
    for a, p in amounts:
        # qualifiers follow the amount ("₹1,500 per order", "₹5k a week"), so classify on the trailing window
        ctx = t[p: p + 32].split(".")[0]
        if any(w in ctx for w in ["per order", "per transaction", "per txn", "each", "single", "per payment"]):
            per_txn = per_txn or a
        elif any(w in ctx for w in ["per week", "a week", "weekly", "/week"]):
            period_cap, period = a, "week"
        elif any(w in ctx for w in ["per day", "a day", "daily", "/day"]):
            period_cap, period = a, "day"
        elif any(w in ctx for w in ["per month", "a month", "monthly", "/month"]):
            period_cap, period = a, "month"
    if per_txn is None and amounts:
        per_txn = min(a for a, _ in amounts)
    if per_txn is None:
        per_txn = 1000.0
        notes.append("no per-transaction amount found; defaulted to ₹1,000")
    if period_cap is None:
        period_cap = per_txn * 3
        notes.append(f"no period cap found; defaulted to 3× per-txn (₹{period_cap:,.0f}/{period})")

    merchants = [m for m in _KNOWN_MERCHANTS if m in t]
    categories = [c for c, hints in _CATEGORY_HINTS.items() if any(h in t for h in hints)]
    allow_new = not any(w in t for w in ["never a new payee", "no new payee", "only these", "only from", "no new merchant", "nowhere else"])
    if not merchants and not categories:
        notes.append("no merchants or categories recognised; agent will be limited to step-up for every payment")
    step_up = None
    m = re.search(r"(?:confirm|ask me|check with me)[^\d₹]{0,30}(?:₹|rs\.?)?\s*(\d[\d,]*k?)", t)
    if m:
        step_up = _amount(m.group(1))

    g = Guardrails(
        per_txn_cap=per_txn,
        period_cap=period_cap,
        period=period,
        allowed_merchants=merchants,
        allow_new_payees=allow_new,
        categories=categories,
        requires_refundability="refund" in t,
        step_up_above=step_up,
    )
    return g, notes


def compile_mandate(text: str) -> tuple[Guardrails, str, list[str]]:
    """Returns (guardrails, compiler_name, notes)."""
    out = generate_json(_SYSTEM, f"User mandate:\n\"\"\"{text}\"\"\"", schema=_SCHEMA)
    notes: list[str] = []
    compiler = "heuristic"
    if out:
        try:
            notes = [str(n) for n in out.pop("notes", [])]
            g = Guardrails(**{k: v for k, v in out.items() if k in Guardrails.model_fields})
            compiler = "gemini"
        except Exception as e:  # schema mismatch → fallback
            notes.append(f"gemini output rejected ({e}); used heuristic compiler")
            g, n2 = heuristic_compile(text)
            notes += n2
    else:
        g, notes = heuristic_compile(text)

    # clamp to rail ceilings
    if g.per_txn_cap > settings.hard_cap_per_txn:
        notes.append(f"per-txn cap clamped from ₹{g.per_txn_cap:,.0f} to rail ceiling ₹{settings.hard_cap_per_txn:,.0f}")
        g.per_txn_cap = settings.hard_cap_per_txn
    month_equiv = {"day": 30, "week": 4.3, "month": 1}[g.period] * g.period_cap
    if month_equiv > settings.hard_cap_per_month:
        clamped = settings.hard_cap_per_month / {"day": 30, "week": 4.3, "month": 1}[g.period]
        notes.append(f"period cap clamped to ₹{clamped:,.0f}/{g.period} to respect ₹{settings.hard_cap_per_month:,.0f}/month ceiling")
        g.period_cap = round(clamped, 2)
    g.allowed_merchants = [m.lower().strip() for m in g.allowed_merchants]
    g.categories = [c.lower().strip() for c in g.categories]
    return g, compiler, notes
