"""The functions each half of the team provides to the other. Contract v1.

Prachi provides build_features, predict and rank_reasons.
Kartik provides decide and score_session (in kya/score.py).

Until the real versions exist, each side uses a fake that returns fixed values
with the same shapes as below. Changing a shape here needs both of us.
"""

# Allowed values of the state fields in a decision
AGENT_CLASSES = ["human", "scripted_bot", "llm_agent"]
ACTIONS = ["allow", "step_up", "hold", "block"]

# identity_state: what the signature check found
#   verified      signature valid, agent key in the registry
#   undeclared    no signature presented (normal for humans and unsigned bots)
#   invalid       signature presented but wrong, or the body was changed   -> R01
#   replayed      valid signature but the nonce was already used          -> R02
#   unknown_agent valid signature from a key that is not in the registry  -> R41
IDENTITY_STATES = ["verified", "undeclared", "invalid", "replayed", "unknown_agent"]

# mandate_state: what the mandate check found
#   none          no mandate presented
#   within        mandate valid and the action is inside every limit
#   violated      payee, category, amount, total or frequency outside the mandate
#   expired       past its expiry, or revoked                            -> R10
#   unverifiable  token present but its issuer signature does not check out
MANDATE_STATES = ["none", "within", "violated", "expired", "unverifiable"]

EVIDENCE_STATES = ["insufficient", "partial", "sufficient"]

# Sensitive actions get a full decision; statement_download is read-only.
SENSITIVE_ACTIONS = ["transfer", "merchant_payment", "add_payee"]


# ---------- Prachi's side ----------

def build_features(events, context):
    """Turn one session into a flat dict of numbers.

    events:  the session's events with seq <= decision_seq (already cut)
    context: the data of the session's decision_context event, or None if
             the log has none

    Returns {feature_name: float}. Missing evidence is a value (for example
    pointer_events = 0), never a crash. Every feature has a one-line comment
    in the code saying what behaviour it measures.
    """
    raise NotImplementedError


def predict(features):
    """Run Model A and Model B on one feature dict.

    Returns:
        {
          "class_probs": {"human": float, "scripted_bot": float, "llm_agent": float},
          "p_fraud": float,                      # calibrated, 0..1
          "contribs": {
              "actor": {feature_name: float},    # Model A, toward the chosen class
              "risk":  {feature_name: float},    # Model B, toward fraud (+) or not (-)
          },
        }
    The bias column of pred_contrib is already dropped.
    """
    raise NotImplementedError


def rank_reasons(contribs, policy_codes):
    """Turn model contributions into ordered reason codes.

    policy_codes: codes the policy already chose, for example ["R12"]; they
                  come first, in the order given.
    Returns a list of {"code", "group", "text"} (see kya/reason_codes.py),
    policy first, then risk, then actor, then evidence. Never empty: with no
    other reason, it ends with R00.
    """
    raise NotImplementedError


# ---------- Kartik's side ----------

def decide(identity_state, mandate_state, p_fraud, amount_paise, evidence_status, action_type):
    """Hard rules first, then the lowest expected cost.

    action_type is one of SENSITIVE_ACTIONS or "statement_download"; it is
    needed because read-only sessions are always allowed and add_payee uses
    the assumed exposure from rules.yaml. (Added to the plan's signature.)

    Returns:
        {
          "action": one of ACTIONS,
          "policy_codes": [code, ...],   # hard-rule codes, or R14 for a cost-rule step-up
          "trust_cap": code or None,     # the hard rule that capped trust, if any
        }
    """
    raise NotImplementedError
