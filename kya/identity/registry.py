"""Agent registry (K8): which agent owns which request-signing key.

Registering a key grants no authority. It only lets the bank say WHO signed a
request. What the agent may do comes from a mandate the customer approved.

Make a demo agent (key file + registry row) from the repo folder:
    python -m kya.identity.registry new agent_shopper "Demo Labs"
The private key goes to data/keys/agents/agent_shopper.pem (git ignores it).
"""

import re
import sys

from bank.backend.db import connect, init_db, now_ms
from kya.identity.keys import agent_key_path, new_private_key, public_key_b64, public_key_from_b64, save_private_key

AGENT_ID = re.compile(r"^agent_[a-z0-9_]{2,40}$")


class RegistryError(ValueError):
    pass


def register_agent(conn, agent_id, public_key, issuer, past_incidents=0):
    """Store an agent's public key (base64). Re-registering the same key is a
    no-op; a different key for an existing agent_id is refused, so nobody can
    take over an agent's name by registering their own key."""
    if not AGENT_ID.match(agent_id or ""):
        raise RegistryError("agent_id must look like agent_shopper (lowercase, digits, _)")
    try:
        public_key_from_b64(public_key)
    except ValueError as err:
        raise RegistryError(f"public_key is not a base64 Ed25519 key: {err}") from None
    if not issuer or len(issuer) > 80:
        raise RegistryError("issuer is required (who runs this agent)")
    existing = get_agent(conn, agent_id)
    if existing:
        if existing["public_key"] != public_key:
            raise RegistryError("agent_id already registered with a different key")
        return existing
    conn.execute("INSERT INTO agents VALUES (?, ?, ?, ?, ?)",
                 (agent_id, public_key, issuer, int(past_incidents), now_ms()))
    return get_agent(conn, agent_id)


def get_agent(conn, agent_id):
    row = conn.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()
    return dict(row) if row else None


def list_agents(conn):
    return [dict(r) for r in conn.execute(
        "SELECT agent_id, issuer, past_incidents, created_ms FROM agents ORDER BY agent_id")]


def new_demo_agent(conn, agent_id, issuer, past_incidents=0):
    """Create (or reuse) the agent's private key file and register its public key."""
    path = agent_key_path(agent_id)
    if not path.exists():
        save_private_key(new_private_key(), path)
    from kya.identity.keys import load_private_key
    key = load_private_key(path)
    register_agent(conn, agent_id, public_key_b64(key), issuer, past_incidents)
    return path


if __name__ == "__main__":
    if len(sys.argv) < 4 or sys.argv[1] != "new":
        sys.exit('usage: python -m kya.identity.registry new <agent_id> "<issuer>" [past_incidents]')
    c = connect()
    init_db(c)
    p = new_demo_agent(c, sys.argv[2], sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 0)
    print(f"registered {sys.argv[2]}; private key in {p}")
