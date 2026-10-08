"""Password hashing on the standard library only.

scrypt is in hashlib, is memory-hard, and needs no third-party package —
which matters because the appliance profile must install without
reaching outside the standard library for anything security-critical.

Parameters follow RFC 7914's interactive-login guidance: n=2^15, r=8,
p=1, costing roughly 32 MB per verification. The cost is deliberate; it
is what makes an offline attack on a stolen hash expensive.

The encoded form carries its own parameters, so raising the cost later
does not invalidate existing hashes — needs_rehash() identifies them and
the next successful sign-in upgrades them transparently.
"""

import hashlib
import hmac
import secrets

SCRYPT_N = 2 ** 15
SCRYPT_R = 8
SCRYPT_P = 1
SALT_BYTES = 16
KEY_BYTES = 32
_PREFIX = "scrypt"


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p,
        dklen=KEY_BYTES, maxmem=132 * n * r + (1 << 20),
    )


def hash_password(password: str) -> str:
    """Return an encoded hash: scrypt$n$r$p$salt_hex$key_hex."""
    if not password:
        raise ValueError("Password must not be empty")
    salt = secrets.token_bytes(SALT_BYTES)
    key = _derive(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    return f"{_PREFIX}${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${key.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time verification. Returns False on any malformed hash
    rather than raising: a corrupt stored hash must read as a failed
    sign-in, not a server error that distinguishes one account from
    another."""
    try:
        prefix, n, r, p, salt_hex, key_hex = encoded.split("$")
        if prefix != _PREFIX:
            return False
        candidate = _derive(password, bytes.fromhex(salt_hex), int(n), int(r), int(p))
    except (ValueError, AttributeError, TypeError):
        return False
    return hmac.compare_digest(candidate, bytes.fromhex(key_hex))


def needs_rehash(encoded: str) -> bool:
    """True when a stored hash uses weaker parameters than current policy."""
    try:
        prefix, n, r, p, _, _ = encoded.split("$")
    except ValueError:
        return True
    return prefix != _PREFIX or (int(n), int(r), int(p)) != (SCRYPT_N, SCRYPT_R, SCRYPT_P)
