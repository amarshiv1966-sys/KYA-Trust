# Assumptions

Every assumption we make goes here. The brief says documented assumptions are not penalised.

1. **Legitimate vs fraudulent.** Legitimate = a human acting for themselves, or an agent acting within the
   customer's authorisation (valid mandate or recorded consent). An APP-scam victim's payment is fraudulent
   (`legit = 0`, actor `human`, `victim = 1`); its cost is reported on its own line because the brief's cost
   matrix names only agents.
2. **Day boundary.** "Payments per day" in a mandate resets at midnight IST (Asia/Kolkata).
3. **Add-payee exposure.** Adding a payee without a payment is treated as ₹10,000 at risk when choosing the
   action. The value lives in `kya/policy/rules.yaml`.
4. **Decision context.** Replay trusts the `decision_context` event only in logs written by our own server.
   Signatures are always re-verified from the raw headers in the log.
5. **Evidence for verified agents.** "Not enough behaviour" (R50, step-up) does not apply to a payment whose
   signature is verified and which is inside a valid mandate: the agent is judged on its identity and the
   customer's consent instead of mouse and keyboard behaviour.
6. **Replay output.** A replay gives the same decision as the live gate in every field except `latency_ms`.
7. **Step-up confirmation (for now).** A step-up creates a single-use approval for exactly that payee, amount
   and currency, valid 5 minutes. Confirming it (passkey, PIN as fallback) is built in a later step; until then
   a step-up payment simply does not go through.
8. **Fake model (until Prachi's models land).** `kya/fusion/fake.py` returns fixed numbers: p_fraud 0.002 for
   sessions with behaviour, 0.005 for verified agents, 0.05 for sessions with none. Every decision says
   `model_version: fake-0`.

