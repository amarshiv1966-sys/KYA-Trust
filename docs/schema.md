# Event schema — version 1

This is interface 1 in `contracts/`. Kartik's bank writes these logs; Prachi's features read them.
Nobody changes this file alone. Any change bumps `schema_version` and is recorded at the bottom.

One session = one file, `data/raw/<session_id>.jsonl`, one JSON object per line, in `seq` order.

## 1. Fields on every event

| Field | Type | Set by | Meaning |
| --- | --- | --- | --- |
| `schema_version` | int | server | Always `1` for this version |
| `session_id` | string | server | `s_` + 12 lowercase hex characters, issued by the server |
| `event_id` | string | client or server | Unique id of this event. Browser events: a random id made by `telemetry.js`. Server events: made by the server. A retried batch reuses the same ids, so the server drops duplicates |
| `seq` | int | server | 1, 2, 3, … in the order the **server received** the event. The only order anyone uses |
| `client_ts_ms` | int or null | client | Browser clock (ms since epoch). `null` on server events. Never used for ordering |
| `server_ts_ms` | int | server | Server clock when the event arrived (ms since epoch) |
| `type` | string | see below | One of the types in section 2 |
| `source` | string | server | `client` (sent by `telemetry.js`) or `server` (written by the bank itself) |
| `page` | string or null | client | Page id from `contracts/element_ids.md`, for example `transfer`. `null` for API-only events |
| `client` | object | client, checked by server | Device and client attributes (section 3) |
| `data` | object | see type | The type-specific fields (section 2) |

The server overwrites `seq`, `server_ts_ms`, `session_id`, `schema_version` and `source` on every event it receives. It never trusts a client's value for these.

## 2. Event types

Types from the brief: `page_view`, `click`, `keystroke`, `form_submit`, `api_call`, `transaction`.
Our own types: `pointer_move`, `scroll`, `decision_context`.

### `page_view` (client)

| Field | Type | Meaning |
| --- | --- | --- |
| `from_page` | string or null | The page before this one |
| `viewport_w`, `viewport_h` | int | Window size in CSS pixels |

### `pointer_move` (client)

Pointer samples are batched so one event holds up to 20 samples, taken at about 20 Hz.

| Field | Type | Meaning |
| --- | --- | --- |
| `points` | list of `[t_ms, x, y]` | `t_ms` is ms since the first sample in this event; `x`, `y` are page coordinates in CSS pixels |

### `click` (client)

Only clicks on elements with a `data-kya-id` are recorded.

| Field | Type | Meaning |
| --- | --- | --- |
| `target` | string | The element's `data-kya-id` |
| `x`, `y` | number | Click position, page coordinates |
| `target_w`, `target_h` | number | The element's size |
| `offset_x`, `offset_y` | number | Click position minus the element's centre. `0, 0` is the exact centre |
| `press_ms` | int or null | Time between mouse-down and mouse-up. `null` when the browser fired a click with no press (typical of scripts) |

A click with no pointer press behind it (a script's `el.click()`, or Enter/Space on a button) has no real position: `x`, `y` are the element's centre, `offset_x`, `offset_y` are `0`, and `press_ms` is `null`.

### `keystroke` (client)

The key itself is **never** recorded. Password fields produce no events at all.

| Field | Type | Meaning |
| --- | --- | --- |
| `target` | string | The field's `data-kya-id` |
| `key_class` | string | `letter`, `digit`, `space`, `backspace`, `enter`, `tab`, `punct` or `other` |
| `dwell_ms` | int | Key-down to key-up |
| `flight_ms` | int or null | Previous key-up to this key-down. `null` for the first key on the page |

### `scroll` (client)

| Field | Type | Meaning |
| --- | --- | --- |
| `dx`, `dy` | number | Scroll distance since the last scroll event |

### `form_submit` (client)

Sent after `telemetry.js` has flushed its buffer, just before the form's request.

| Field | Type | Meaning |
| --- | --- | --- |
| `form` | string | The form's `data-kya-id`, for example `transfer.form` |
| `fields_filled` | int | Fields with a value when submitted |
| `fields_without_keys` | int | Filled fields that got no `keystroke` events (pasted, autofilled or set by a script) |
| `paste_count` | int | Paste actions on this form |

Password fields (`login.password`, `stepup.pin`) are left out of `fields_filled` and `fields_without_keys`, because they never produce key events.

### `api_call` (server)

Written for **every** API request that carries a session, from browsers and API-only clients alike, at the moment it arrives. A browser session starts before login (our pages call `POST /api/session/start` on load), so the login page's own clicks and keys are in the same session as everything after it.

| Field | Type | Meaning |
| --- | --- | --- |
| `method` | string | `GET`, `POST`, … |
| `path` | string | For example `/api/transfer` |
| `query` | string | Raw query string, `""` if none |
| `status` | null | Always `null` for now: the event is written when the request **arrives**, before the response exists, so that a `transaction` event can point back to it |
| `channel` | string | `browser` (request came with the session cookie from our pages) or `api` |
| `headers` | object | Only these, raw: `user_agent`, `accept_language`, `signature_input`, `signature`, `content_digest`, `kya_mandate` (the mandate JWT), `kya_mandate_id`, `idempotency_key`. Missing ones are `null` |
| `content_digest_ok` | bool or null | Whether the `Content-Digest` header matched the raw body when the request arrived. `null` if there was no such header. Recorded because `body` below has free-text fields removed, so a replay cannot recompute the hash |
| `body` | object or null | The request body with every free-text field removed (names, notes). Amounts, ids and categories stay |

The raw signature headers are kept so a replay can **re-verify** the signature from the log alone.

### `transaction` (server)

Written by the payment gate when a sensitive action arrives, **before** it is scored. Its `seq` is the session's `decision_seq` in `labels.csv`.

| Field | Type | Meaning |
| --- | --- | --- |
| `action` | string | `transfer`, `merchant_payment`, `add_payee` or `statement_download` |
| `amount_paise` | int | Amount in paise (₹1 = 100 paise). `0` for `add_payee` and `statement_download` |
| `currency` | string | Always `INR` for now |
| `payee_id` | string or null | Canonical payee id, for example `py_000123`, or merchant id `mr_grocermart` |
| `new_payee` | bool | True if this account has never paid this payee before |
| `merchant_category` | string or null | One of the categories in `contracts/element_ids.md`. `null` for person-to-person transfers |
| `mandate_token` | string or null | The attached mandate JWT, if any |
| `mandate_id` | string or null | The mandate id the signature names, if any |
| `idempotency_key` | string or null | From the request header |
| `api_call_seq` | int | `seq` of the `api_call` event for this request |

### `decision_context` (server)

Written by the gate right after the `transaction` event and before scoring. It freezes the bank's state at that moment so a replay gives the same answer later, even after a mandate is revoked. Signatures are **not** taken from here: the scorer re-verifies them from the raw headers of the `api_call` event, using `agent.public_key`.

| Field | Type | Meaning |
| --- | --- | --- |
| `decision_seq` | int | `seq` of the `transaction` event being decided |
| `account_id` | string | The account the money would leave |
| `user_id` | string | The account holder |
| `mandate` | object or null | `null` if no mandate was presented, otherwise: `mandate_id`, `status` (`active`, `revoked`, `expired`, `unknown`), `consumed_paise`, `payments_today` (since midnight IST) |
| `history` | object | The account's past payments **before** this session: `payment_count`, `median_amount_paise`, `mad_amount_paise` (median absolute deviation), `payees_seen` (list of payee ids), `categories_seen` (list), `last_payment_ts_ms` (or null) |
| `provenance` | object | `device_accounts_before`: how many other accounts this device logged into before now. `agent`: `null`, or `agent_id`, `public_key` (base64 Ed25519), `issuer`, `past_incidents` (int) from the registry |
| `issuer_public_key` | string | The bank's mandate-issuer public key (base64), so the mandate can be verified offline |
| `versions` | object | `policy_version`, `model_version` |

## 3. The `client` object

Sent by the browser on every client event. The server fills it for API-only requests from the request itself. A browser session's first event is the server's `session/start` record, written before the browser has sent anything, so **read device fields from the first event with `source: "client"`** and fall back to the first event only when there is none (API-only sessions). Coarse classes only: nothing that identifies a person.

| Field | Type | Meaning |
| --- | --- | --- |
| `device_id` | string | Random id kept in a cookie by our bank, so device reuse can be counted. Not a fingerprint |
| `device_class` | string | `desktop`, `laptop`, `phone`, `tablet` or `unknown` |
| `os_family` | string | `windows`, `macos`, `linux`, `android`, `ios` or `other` |
| `browser_family` | string | `chrome`, `edge`, `firefox`, `safari`, `none` (API client) or `other` |
| `input_type` | string | `mouse`, `touch`, `keyboard_only` or `unknown` |
| `webdriver` | bool or null | `navigator.webdriver` as the page sees it. `null` for API-only clients |
| `languages_count` | int or null | Length of `navigator.languages` (headless browsers often report 0) |
| `timezone_offset_min` | int or null | The browser's offset from UTC |

## 4. What makes input malformed vs sparse

`score_session(events)` checks the list before doing anything else.

**Malformed → error, no decision:**
- not a list of objects
- any event missing a field from section 1
- `schema_version` other than `1`
- an unknown `type`
- `seq` not strictly increasing, or events from more than one `session_id`
- a `transaction` event missing `action`, `amount_paise` or `currency`, or an amount that is not an integer

**Sparse → decision with `evidence_status`:**
- `insufficient`: no `click`, `keystroke` or `pointer_move` events and fewer than 3 `api_call` events
- `partial`: some behaviour events but fewer than 20 in total, or no behaviour events and 3 or more `api_call` events (an API-only client, judged on request timing)
- `sufficient`: 20 or more behaviour events

Sessions with no pointer events (API-only bots and agents) are normal input, not an error.

## 5. The cut at the decision

Features for a decision use only events with `seq` at or below `decision_seq`, plus the `decision_context` event. `telemetry.js` flushes its buffer before every form submit, so the last seconds of behaviour arrive before the `transaction` event. Training uses the same cut, so offline numbers match the live gate.

## 6. Output of `score_session`

```json
{
  "session_id": "s_3f9a1c2b7d10",
  "decision_seq": 41,
  "agent_class": "llm_agent",
  "class_probs": {"human": 0.03, "scripted_bot": 0.05, "llm_agent": 0.92},
  "p_fraud": 0.10,
  "base_trust": 90,
  "trust_score": 20,
  "trust_cap": "R12",
  "action": "hold",
  "reason_codes": [
    {"code": "R12", "group": "policy", "text": "Merchant is not on the mandate's allowed list"},
    {"code": "R30", "group": "risk", "text": "First payment to this payee"},
    {"code": "R60", "group": "actor", "text": "Verified agent, signature valid"}
  ],
  "identity_state": "verified",
  "mandate_state": "violated",
  "evidence_status": "sufficient",
  "schema_version": 1,
  "model_version": "fake-0",
  "policy_version": "p-0",
  "latency_ms": 14.2
}
```

The allowed values of every state field, and the text of every reason code, live in `kya/interfaces.py` and `kya/reason_codes.py`.

## Change log

- **v1 (22 Nov 2026):** first version.
- **v1, 23 Nov 2026 (K6):** `api_call.status` is `null` (written on arrival). Sessions start at `/api/session/start`, before login. No change to any field name, so `schema_version` stays 1.
- **v1, 23 Nov 2026 (K7):** `telemetry.js` sends client events. Clarified: clicks with no press, password fields in `form_submit` counts, and which event to read device fields from. No field changes.
- **v1, 23 Nov 2026 (K8):** `api_call` gains `content_digest_ok` and the `kya_mandate` header (the token, signed by the agent's request signature). Signed agents send `KYA-Mandate` and `KYA-Mandate-Id`; see `kya/identity/signing.py`. Added fields only, so `schema_version` stays 1.
