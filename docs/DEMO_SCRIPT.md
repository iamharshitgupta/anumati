# Anumati — 3-minute demo script

Target: 2:50. Record the console at 1440×900, API on Cloud Run with Gemini enabled. Rehearse once with `?` — every beat below is one click.

| Time | Screen | Say |
|---|---|---|
| 0:00–0:20 | Title card → architecture.png | "NPCI is about to let AI agents pay on UPI without asking you each time. Google's AP2 proves you *authorised* the agent. Nothing proves the agent wasn't steered between your instruction and the rail. Anumati is the gateway that answers that question for every payment — and signs the evidence." |
| 0:20–0:45 | **Mandates** tab · type mandate · Compile · Sign | "You write one sentence. Gemini compiles it into enforceable guardrails — caps, merchants, no new payees, confirm above ₹1,500 — clamped to UPI Circle ceilings. You sign; now it's policy." |
| 0:45–1:00 | **Sandbox** · *Clean order* · Run | "KiranaBot does the weekly groceries. Policy passes, Gemini sees no steering. Approved in under a second, receipt issued." |
| 1:00–1:35 | *Hidden-text injection* · expand hidden content · Run | "Same page, but a hidden div tells the agent the UPI id 'migrated' — to a mule. The naive agent obeys. Anumati: the VPA isn't FreshKart's verified one, the mandate forbids new payees, the payee is on the suspect registry — and the injected text is quoted verbatim in the audit. Blocked before anything reached the rail." |
| 1:35–1:55 | *Review-text injection* · Run → **Step-ups** tab · Decline | "A poisoned review says 12 jars of ghee are mandatory. Borderline, so Anumati holds it and asks the human — one tap, with the reasons. Declined." |
| 1:55–2:15 | **Receipts** · open the block receipt · Verify chain | "Every verdict is a signed, hash-chained receipt: what the mandate said, what the agent attempted, every finding and its evidence. Anyone can verify it offline." |
| 2:15–2:40 | **Disputes** · raise as *merchant* · Replay | "The merchant disputes. Anumati replays the receipt and drafts the attribution: content provider, high confidence, injected instruction as evidence. The analyst closes the case." |
| 2:40–2:50 | `eval/RESULTS.md` table | "On 44 synthetic cases Anumati lands the right verdict every time — zero false flags, even on four hard-negative orders built to trip a naive detector. Deterministic rules alone catch most attacks; the Gemini audit adds the ones no rule can see — content that steers the agent without breaking a single limit. Firebase, Firestore, Cloud Run, Gemini — one gateway call for any agent on UPI." |

## Recording checklist
- `curl $API/healthz` shows `semantic_engine: gemini` before recording.
- Run `POST /admin/seed` once; reload console so the mandate dropdown is populated.
- Keep the "agent" dropdown on *naive* for the injection beats; switch to *Gemini-driven* once at the end only if time allows ("frontier models resist crude injections — Anumati is for the ones that don't, and for the subtler attacks").
- Mute notifications; the toast on step-up is part of the demo.
- Export: 1080p, ≤ 3:00, captions on.
