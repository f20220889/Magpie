"""Password hashing and token helpers (standard library only).

Uses PBKDF2-HMAC-SHA256 with a per-password random salt. The stored format is
``pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>`` so the iteration count can
be raised over time without breaking existing hashes. Verification is constant
time. No third-party crypto dependency is required.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

_ALGO = "pbkdf2_sha256"
_ITERATIONS = 240_000
_SALT_BYTES = 16
MIN_PASSWORD_LENGTH = 8


def hash_password(password: str, iterations: int = _ITERATIONS) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"password must be at least {MIN_PASSWORD_LENGTH} characters"
        )
    salt = secrets.token_bytes(_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{_ALGO}${iterations}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != _ALGO:
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk.hex(), hash_hex)


def new_token() -> str:
    """Return a cryptographically strong, URL-safe session/state token."""
    return secrets.token_urlsafe(32)
