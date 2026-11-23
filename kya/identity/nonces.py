"""Nonce store (K8): each signed request may be used once.

A nonce is a random string the agent puts inside its signature. If the same
agent sends the same nonce twice, the second request is a replay (R02), even
though its signature is valid. The gate (K9) calls consume_nonce() inside its
BEGIN IMMEDIATE transaction, so two copies arriving together cannot both pass.
"""

import sqlite3


def consume_nonce(conn, agent_id, nonce, seen_ms):
    """Record the nonce. True the first time, False if it was already used."""
    try:
        conn.execute("INSERT INTO nonces VALUES (?, ?, ?)", (agent_id, nonce, seen_ms))
        return True
    except sqlite3.IntegrityError:
        return False


def nonce_seen(conn, agent_id, nonce):
    return conn.execute("SELECT 1 FROM nonces WHERE agent_id = ? AND nonce = ?",
                        (agent_id, nonce)).fetchone() is not None
