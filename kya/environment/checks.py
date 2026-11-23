"""Environment checks (K11): facts about the client, not about behaviour.

They only add reason codes that explain the agent class. They never decide
an action alone: a legitimate assistant may well run in an automated browser.
"""

from kya.policy.engine import RULES

CODES = RULES["environment"]


def environment_codes(events):
    """R20 if the browser says it is automated, R21 if there were API calls
    but no page activity at all (an API-only client)."""
    codes = []
    browser = [e for e in events if e["source"] == "client"]
    if browser and browser[0]["client"].get("webdriver") is True:
        codes.append(CODES["automation_flag"])
    calls = [e for e in events if e["type"] == "api_call"]
    if calls and not browser:
        codes.append(CODES["api_without_page"])
    return codes
