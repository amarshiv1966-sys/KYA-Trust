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
