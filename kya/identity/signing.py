"""Agent request signatures under RFC 9421 (K8), using http-message-signatures.

An agent signs each request with its own Ed25519 key. The signature covers:
  @method, @path, @query          what it is asking for
  content-digest                  a SHA-256 hash of the body (amount, payee...)
  kya-mandate, kya-mandate-id     the mandate token it acts under, and its id
  created, nonce, keyid           when, a one-time random value, and who
Change any of these after signing and the signature no longer checks out.

Prachi's signed bots use sign_request(). The gate (K9) and the offline replay
use verify_request(), which works from the raw headers kept in the api_call
event, so a replay re-checks the signature itself instead of trusting a flag.

Time is always passed in (now_ms), never read from the clock here. Live, it is
when the request arrived; in a replay it is the same value from the log, so a
signature that was fresh then is still judged fresh years later.
"""

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import jwt
from http_message_signatures import HTTPMessageSigner, HTTPMessageVerifier, InvalidSignature, algorithms
from http_message_signatures.exceptions import HTTPMessageSignaturesException
from http_message_signatures.resolvers import HTTPSignatureKeyResolver

from kya.identity.keys import public_key_from_b64

MAX_AGE_S = 300      # a signature older than 5 minutes is refused
MAX_SKEW_S = 60      # or one from more than a minute in the future


class _Message:
    """The minimal request object the library reads: method, url, headers."""

    def __init__(self, method, path, query, headers):
        self.method = method.upper()
        self.url = "http://bank" + path + (("?" + query) if query else "")
        self.headers = headers


class _OneKey(HTTPSignatureKeyResolver):
    def __init__(self, private=None, public=None):
        self.private, self.public = private, public

    def resolve_private_key(self, key_id):
        return self.private

    def resolve_public_key(self, key_id):
        return self.public


def content_digest(body):
    """Content-Digest header value for these body bytes (sha-256 only)."""
    return "sha-256=:" + base64.b64encode(hashlib.sha256(body).digest()).decode() + ":"


def sign_request(method, path, body, *, agent_id, private_key, mandate_token=None, mandate_id=None,
                 query="", nonce=None, created_s=None):
    """Return the headers an agent adds to its request:
    Content-Digest, Signature-Input, Signature, and with a mandate also
    KYA-Mandate (the token) and KYA-Mandate-Id.

    body: the exact bytes that will be sent (b"" for none). Send these bytes
          as-is; re-serializing the JSON would change the digest.
    mandate_token: the JWT the customer's bank issued. Its mandate_id is read
          from it, so the two always match.
    """
    headers = {"Content-Digest": content_digest(body)}
    covered = ["@method", "@path", "@query", "content-digest"]
    if mandate_token:
        mandate_id = jwt.decode(mandate_token, options={"verify_signature": False})["mandate_id"]
        headers["KYA-Mandate"] = mandate_token
        covered.append("kya-mandate")
    if mandate_id:
        headers["KYA-Mandate-Id"] = mandate_id
        covered.append("kya-mandate-id")
    created = datetime.fromtimestamp(created_s if created_s is not None else time.time(), timezone.utc)
    signer = HTTPMessageSigner(signature_algorithm=algorithms.ED25519, key_resolver=_OneKey(private=private_key))
    msg = _Message(method, path, query, headers)
    signer.sign(msg, key_id=agent_id, created=created, nonce=nonce or secrets.token_hex(12),
                label="kya", covered_component_ids=covered, use_existing_digest=True)
    return dict(msg.headers)


@dataclass
class SignatureCheck:
    state: str                 # an IDENTITY_STATES value, before the nonce check
    agent_id: str | None = None
    nonce: str | None = None
    mandate_id: str | None = None
    mandate_token: str | None = None
    created_s: int | None = None
    codes: list = field(default_factory=list)
    detail: str = ""


def _header(headers, name):
    for k, v in headers.items():
        if k.lower() == name and v is not None:
            return v
    return None


def verify_request(method, path, query, headers, *, lookup_key, now_ms, digest_ok):
    """Check a request's signature.

    headers:    the raw request headers (a dict; names in any case)
    lookup_key: agent_id -> registered public key (base64), or None if unknown
    digest_ok:  True/False/None, whether Content-Digest matched the body when
                the request arrived (the api_call event records it, because
                the logged body has free-text fields removed)

    Returns a SignatureCheck. The nonce is NOT consumed here; the gate does
    that inside its transaction and turns a reused nonce into "replayed" (R02).
    """
    sig_input = _header(headers, "signature-input")
    sig = _header(headers, "signature")
    if not sig_input and not sig:
        return SignatureCheck("undeclared", detail="no signature presented")
    if not sig_input or not sig:
        return SignatureCheck("invalid", codes=["R01"], detail="signature headers incomplete")

    # Who claims to have signed? Read keyid without trusting it yet.
    keyid = None
    for part in sig_input.split(";"):
        part = part.strip()
        if part.startswith("keyid="):
            keyid = part[len("keyid="):].strip('"')
    public_b64 = lookup_key(keyid) if keyid else None
    if public_b64 is None:
        return SignatureCheck("unknown_agent", agent_id=keyid, codes=["R41"],
                              detail="signing key is not in the registry")

    present = {k.lower(): v for k, v in headers.items() if v is not None}
    msg = _Message(method, path, query, {k: v for k, v in present.items()
                                          if k in ("signature-input", "signature", "content-digest",
                                                   "kya-mandate", "kya-mandate-id")})
    required = ["@method", "@path", "@query", "content-digest"]
    for name in ("kya-mandate", "kya-mandate-id"):
        if name in present:
            required.append(name)   # a mandate header the agent did not sign is rejected
    verifier = HTTPMessageVerifier(signature_algorithm=algorithms.ED25519,
                                   key_resolver=_OneKey(public=public_key_from_b64(public_b64)))
    try:
        # max_age=None: we check freshness ourselves against now_ms (see top)
        results = verifier.verify(msg, max_age=None, require_components=required)
    except (InvalidSignature, HTTPMessageSignaturesException, ValueError) as err:
        return SignatureCheck("invalid", agent_id=keyid, codes=["R01"], detail=f"signature does not verify: {err}")
    params = results[0].parameters
    created, nonce = params.get("created"), params.get("nonce")
    if not isinstance(created, int) or not nonce:
        return SignatureCheck("invalid", agent_id=keyid, codes=["R01"], detail="signature has no created time or nonce")
    now_s = now_ms / 1000
    if created < now_s - MAX_AGE_S or created > now_s + MAX_SKEW_S:
        return SignatureCheck("invalid", agent_id=keyid, nonce=nonce, created_s=created, codes=["R01"],
                              detail="signature is too old or from the future")
    if digest_ok is not True:
        return SignatureCheck("invalid", agent_id=keyid, nonce=nonce, created_s=created, codes=["R01"],
                              detail="body does not match the signed Content-Digest")
    return SignatureCheck("verified", agent_id=keyid, nonce=nonce, mandate_id=present.get("kya-mandate-id"),
                          mandate_token=present.get("kya-mandate"),
                          created_s=created, detail="signature valid")
