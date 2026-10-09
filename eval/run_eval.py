"""Runs eval/cases.json through Anumati and the caps-only baseline.

Usage:
    python eval/run_eval.py                   # heuristic semantic engine (deterministic)
    GOOGLE_API_KEY=... python eval/run_eval.py # Gemini semantic engine

Outputs eval/results.json and eval/RESULTS.md. Each case runs against a fresh
in-memory store seeded with the demo mandate, so cases are independent.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("ANUMATI_STORE", "memory")
os.environ.setdefault("ANUMATI_SEED", "false")

from app.engine import baseline_caps_only, decide  # noqa: E402
from app.gemini import engine_name  # noqa: E402
from app.models import CartItem, PaymentRequest, TraceStep  # noqa: E402
from app.seed import DEMO_AGENT, DEMO_MANDATE_ID, DEMO_USER, seed  # noqa: E402
from app.store import MemoryStore, set_store  # noqa: E402

FLAG = {"STEP_UP", "BLOCK"}


def to_request(r: dict) -> PaymentRequest:
    return PaymentRequest(
        agent_id=DEMO_AGENT, mandate_id=DEMO_MANDATE_ID, user_id=DEMO_USER,
        payee_vpa=r["payee_vpa"], payee_name=r["payee_name"], merchant=r.get("merchant"), amount=r["amount"],
        category=r.get("category"), cart=[CartItem(**c) for c in r.get("cart", [])],
        agent_trace=[TraceStep(step=i + 1, kind="observe" if i == 0 else "think", content=t) for i, t in enumerate(r.get("agent_trace", []))],
        consumed_content=r.get("consumed_content"), simulated=True,
    )


def outcome_ok(expect: str, verdict: str) -> bool:
    return {"pass": verdict == "APPROVE", "flag": verdict in FLAG, "block": verdict == "BLOCK"}[expect]


def main() -> int:
    cases = json.loads((ROOT / "eval" / "cases.json").read_text())
    rows = []
    for c in cases:
        store = MemoryStore()
        set_store(store)
        seed(store)
        req = to_request(c["request"])
        n = c.get("sequence", 1)
        t0 = time.perf_counter()
        verdict, base_verdict, findings = None, None, []
        for _ in range(n):
            d = decide(req, store)
            verdict, findings = d.verdict, [f.code for f in d.findings]
            base_verdict = baseline_caps_only(req, store)
            if verdict == "BLOCK":
                break
        ms = int((time.perf_counter() - t0) * 1000)
        rows.append({
            "id": c["id"], "pattern": c["pattern"], "label": c["label"], "expect": c["expect"],
            "anumati": verdict, "anumati_ok": outcome_ok(c["expect"], verdict),
            "baseline": base_verdict, "baseline_ok": outcome_ok(c["expect"], base_verdict),
            "findings": findings, "risk": d.risk_score, "latency_ms": ms,
        })

    attacks = [r for r in rows if r["label"] == "attack"]
    benign = [r for r in rows if r["label"] == "benign"]
    summary = {
        "semantic_engine": engine_name(),
        "cases": len(rows), "attacks": len(attacks), "benign": len(benign),
        "anumati": {
            "attack_catch_rate": round(sum(r["anumati"] in FLAG for r in attacks) / len(attacks), 3),
            "attack_block_rate": round(sum(r["anumati"] == "BLOCK" for r in attacks) / len(attacks), 3),
            "expected_outcome_rate": round(sum(r["anumati_ok"] for r in rows) / len(rows), 3),
            "benign_false_flag_rate": round(sum(r["anumati"] in FLAG and r["expect"] == "pass" for r in benign) / max(1, sum(r["expect"] == "pass" for r in benign)), 3),
            "p50_latency_ms": sorted(r["latency_ms"] for r in rows)[len(rows) // 2],
        },
        "baseline_caps_only": {
            "attack_catch_rate": round(sum(r["baseline"] in FLAG for r in attacks) / len(attacks), 3),
            "attack_block_rate": round(sum(r["baseline"] == "BLOCK" for r in attacks) / len(attacks), 3),
            "expected_outcome_rate": round(sum(r["baseline_ok"] for r in rows) / len(rows), 3),
            "benign_false_flag_rate": round(sum(r["baseline"] in FLAG and r["expect"] == "pass" for r in benign) / max(1, sum(r["expect"] == "pass" for r in benign)), 3),
        },
    }
    per = defaultdict(lambda: {"n": 0, "anumati_caught": 0, "baseline_caught": 0, "anumati_expected": 0})
    for r in rows:
        p = per[r["pattern"]]
        p["n"] += 1
        p["anumati_caught"] += r["anumati"] in FLAG
        p["baseline_caught"] += r["baseline"] in FLAG
        p["anumati_expected"] += r["anumati_ok"]

    (ROOT / "eval" / "results.json").write_text(json.dumps({"summary": summary, "per_pattern": per, "rows": rows}, indent=1))

    md = [f"# Anumati eval results\n", f"Semantic engine: **{summary['semantic_engine']}** · {summary['cases']} cases ({summary['attacks']} attack / {summary['benign']} benign)\n",
          "| Metric | Anumati | Caps-only baseline |", "|---|---|---|"]
    for k, label in [("attack_catch_rate", "Attacks flagged (STEP_UP or BLOCK)"), ("attack_block_rate", "Attacks blocked outright"),
                     ("expected_outcome_rate", "Cases landing on the expected verdict"), ("benign_false_flag_rate", "Benign orders wrongly flagged")]:
        md.append(f"| {label} | {summary['anumati'][k]:.0%} | {summary['baseline_caps_only'][k]:.0%} |")
    md += ["", f"p50 decision latency: {summary['anumati']['p50_latency_ms']} ms", "", "## Per pattern", "", "| Pattern | n | Anumati flagged | Anumati expected verdict | Baseline flagged |", "|---|---|---|---|---|"]
    for name, p in sorted(per.items()):
        md.append(f"| {name} | {p['n']} | {p['anumati_caught']}/{p['n']} | {p['anumati_expected']}/{p['n']} | {p['baseline_caught']}/{p['n']} |")
    md += ["", "## Misses", ""]
    misses = [r for r in rows if not r["anumati_ok"]]
    md += [f"- `{r['id']}` expected {r['expect']}, got {r['anumati']} (risk {r['risk']}, findings {r['findings']})" for r in misses] or ["None."]
    (ROOT / "eval" / "RESULTS.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))
    return 0 if not misses else 1


if __name__ == "__main__":
    sys.exit(main())
