# Contracts — version 1

The six interfaces between Kartik's half and Prachi's half. **Nobody changes them alone.** A change needs both of us, bumps the version, and is noted in the file's change log.

| # | Interface | Where | Owner |
| --- | --- | --- | --- |
| 1 | Event format | `docs/schema.md` | Kartik |
| 2 | Element ids, merchants, categories | `contracts/element_ids.md` | Kartik |
| 3 | Model interface (`build_features`, `predict`, `rank_reasons`, `decide`) | `kya/interfaces.py`, `kya/reason_codes.py` | Both |
| 4 | Signing helper and registry (`issue_mandate`, `sign_request`, `register_agent`) | `kya/identity/` (built in K8) | Kartik |
| 5 | Labels | `docs/labels.md` (P1) | Prachi |
| 6 | Splits | `data/splits.yaml` (P1) | Prachi |

## Sample logs

`samples/` holds three invented sessions that follow the schema, so features can be built before the bank works:

- `human_transfer.jsonl`: a person logs in and sends ₹2,500 to a saved payee
- `signed_agent_merchant.jsonl`: a signed LLM agent buys from the mock shop inside its mandate (₹1,499)
- `http_bot_statement.jsonl`: an unsigned HTTP script logs in and downloads a statement

Regenerate them with `python contracts/samples/make_samples.py`. The signature, digest and key values in the agent sample are placeholders until K8.

`pytest tests/test_contracts.py` checks the samples against the schema.
