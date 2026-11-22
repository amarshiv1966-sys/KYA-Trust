"""Ed25519 keys (K8).

Two kinds of key, kept apart on purpose:
- the bank's ISSUER key signs mandates. Only the bank has it.
- each agent's REQUEST-SIGNING key signs that agent's HTTP requests. The agent
  keeps the private half; the bank's registry stores only the public half.

Private keys live in data/keys/ (KYA_KEYS_DIR overrides), which git ignores.
Public keys travel as base64 of the raw 32 bytes.
"""

import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

ROOT = Path(__file__).resolve().parents[2]
ISSUER_FILE = "issuer_ed25519.pem"


def keys_dir():
    return Path(os.environ.get("KYA_KEYS_DIR", ROOT / "data" / "keys"))


def new_private_key():
    return Ed25519PrivateKey.generate()


def save_private_key(key, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    path.write_bytes(pem)


def load_private_key(path):
    return serialization.load_pem_private_key(Path(path).read_bytes(), password=None)


def public_key_b64(key):
    """base64 of the raw public key. Accepts a private or a public key."""
    if isinstance(key, Ed25519PrivateKey):
        key = key.public_key()
    raw = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def public_key_from_b64(text):
    raw = base64.b64decode(text, validate=True)
    if len(raw) != 32:
        raise ValueError("an Ed25519 public key is 32 bytes")
    return Ed25519PublicKey.from_public_bytes(raw)


def load_issuer_key():
    """The bank's mandate-issuer key. Created on first use."""
    path = keys_dir() / ISSUER_FILE
    if not path.exists():
        save_private_key(new_private_key(), path)
    return load_private_key(path)


def agent_key_path(agent_id):
    return keys_dir() / "agents" / f"{agent_id}.pem"
