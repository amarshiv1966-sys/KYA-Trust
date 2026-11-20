"""Every reason code the system can return, with its group and plain text.

Part of contract v1. Policy codes always come first in a decision, then risk,
then actor, then evidence. The text is what a fraud analyst reads, so keep it
short and plain.
"""

# code -> (group, text)
REASON_CODES = {
    # policy: hard rules and the cost rule
    "R01": ("policy", "Request signature is invalid or the request was altered"),
    "R02": ("policy", "This signed request was already used (replay)"),
    "R10": ("policy", "Mandate is expired or revoked"),
    "R11": ("policy", "Amount is above the mandate's limit"),
    "R12": ("policy", "Payee or merchant is not on the mandate's allowed list"),
    "R13": ("policy", "Too many payments today under this mandate"),
    "R14": ("policy", "Extra check chosen because of the payment's size and risk"),
    # actor: who is acting
    "R20": ("actor", "Browser reports it is controlled by automation"),
    "R21": ("actor", "API calls with no page activity"),
    "R22": ("actor", "Gaps between actions are machine-regular"),
    "R23": ("actor", "Clicks land on the exact centre of buttons"),
    "R24": ("actor", "Long pauses followed by instant, exact actions"),
    "R25": ("actor", "Fields filled with no keystrokes"),
    "R60": ("actor", "Verified agent acting inside its mandate"),
    # risk: is this payment risky
    "R30": ("risk", "First payment to this payee"),
    "R31": ("risk", "Amount is far above this customer's usual payments"),
    "R32": ("risk", "Payment within seconds of logging in"),
    "R33": ("risk", "Merchant category this customer has never used"),
    "R40": ("risk", "This device was used on many accounts before"),
    "R41": ("risk", "Agent is unknown or has past incidents"),
    # evidence
    "R34": ("evidence", "Customer has little payment history"),
    "R50": ("evidence", "Not enough behaviour seen to judge who is acting"),
    "R00": ("evidence", "No risk signals found"),
}

GROUP_ORDER = ["policy", "risk", "actor", "evidence"]


def reason(code):
    """Return one reason as the dict that goes into a decision."""
    group, text = REASON_CODES[code]
    return {"code": code, "group": group, "text": text}
