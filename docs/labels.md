# labels.csv — spec (contracts v1)

One row per session. Labels and metadata NEVER go into model inputs.
The split column is copied from `data/splits.yaml` by `group_id`; it is never chosen per session.

| Column | Type | Allowed values | Filled by | Meaning |
| --- | --- | --- | --- | --- |
| session_id | str | `s_` + id | generator / recorder | Matches the log file name |
| decision_seq | int | ≥ 0 | generator / recorder | `seq` of the one scored action (transfer, merchant payment or add payee). Read-only sessions: seq of the last event |
| actor | str | human, scripted_bot, llm_agent | generator / recorder | Who started the scored action (not who started the session) |
| legit | int | 0, 1 | scenario | 1 = human acting for themselves, or agent within the customer's authorisation |
| authorized | int | 0, 1 | scenario | 1 = valid mandate or recorded consent covers the action. Can be 1 with legit = 0 (compromised agent) |
| victim | int | 0, 1 | scenario | 1 = APP scam: human tricked, actor = human, legit = 0 |
| handover_seq | int or empty | | generator | Takeover only: seq where the agent took over |
| typology | str | none, prompt_injection, in_scope_compromise, app_scam, takeover, mule | scenario | |
| group_id | str | key in splits.yaml | generator / recorder | Volunteer ID (P01…), script family, or agent config |
| split | str | train, dev, test | lookup | From splits.yaml |
| hard_mode | int | 0, 1 | generator | Human-like timing bot/agent |
| unseen_framework | int | 0, 1 | generator | Stagehand run |
| unseen_attack | int | 0, 1 | generator | New payee, allowed category, unusual amount |
| channel | str | browser, api | generator / recorder | |
| device_class | str | desktop, laptop, phone | recorder | Coarse only |
| input_type | str | mouse, touchpad, touch, keyboard_only, none | recorder | |
| browser | str | chromium, firefox, webkit, chrome, safari, none | recorder | |
| framework | str | none, playwright, selenium, httpx, browser_use, stagehand | generator | |
| config_id | str | | generator | Exact bot/agent config |
| seed | int or empty | | generator | Empty for humans and LLM runs that can't be replayed |
| generator_version | str | e.g. g-0.1 | generator | |

## Consistency checks (run by the generator before writing a row)

- `victim = 1` ⇒ `actor = human`, `legit = 0`, `typology = app_scam`
- `typology = takeover` ⇒ `handover_seq` is set and `< decision_seq`
- `typology = in_scope_compromise` ⇒ `authorized = 1`, `legit = 0`
- `typology = none` ⇒ `legit = 1`
- `unseen_framework = 1` or `unseen_attack = 1` ⇒ `split = test`
- `group_id` must exist in splits.yaml
