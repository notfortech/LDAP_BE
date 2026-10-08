"""Opaque bearer tokens.

A token is 32 random bytes shown to the client once. Only its SHA-256
digest is stored, so a database disclosure yields no usable credential.
SHA-256 without a work factor is correct here and would not be for a
password: the token already has 256 bits of entropy, so there is no
guess space to slow an attacker down in.
"""

import hashlib
import secrets

TOKEN_BYTES = 32


def issue_token() -> tuple[str, str]:
    """Return (plaintext, digest). The plaintext is never stored."""
    plaintext = secrets.token_urlsafe(TOKEN_BYTES)
    return plaintext, hash_token(plaintext)


def hash_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
