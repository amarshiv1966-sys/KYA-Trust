# Scenario templates

One file per scenario. The generator (and volunteer recorders) read these to know
what task to run and which labels to write. Scenario text NEVER goes into event logs.

Fields:
- task: what the actor does (instructions for bot/agent/volunteer)
- action: the scored decision — transfer | merchant_payment | add_payee | read_only
- amount_inr: [min, max] range, sampled uniformly then converted to paise
- payee: existing | new | fraud
- merchant_category: allowed | not_allowed | n/a (relative to the mandate)
- labels: values copied into labels.csv (actor, legit, authorized, victim, typology)
- families: which group_ids may run this scenario (see data/splits.yaml)
