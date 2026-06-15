"""Fernet symmetric encryption for at-rest secrets (LinkedIn tokens, OAuth state).

`APP_SECRET_KEY` MUST be a valid Fernet key — 32 url-safe base64 bytes. Generate with:

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Rotating the key invalidates every existing ciphertext (stored LinkedIn tokens, in-flight
OAuth state). Don't rotate after first use unless you also re-issue all tokens.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


class CryptoError(Exception):
    pass


def _fernet() -> Fernet:
    if not settings.APP_SECRET_KEY:
        raise CryptoError("APP_SECRET_KEY is not set")
    try:
        return Fernet(settings.APP_SECRET_KEY.encode())
    except (ValueError, TypeError) as e:
        raise CryptoError(f"APP_SECRET_KEY is not a valid Fernet key: {e}") from e


def encrypt(plaintext: str) -> str:
    """Encrypt a string. Returns base64-ASCII ciphertext safe for TEXT columns."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a base64-ASCII ciphertext produced by `encrypt`."""
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as e:
        raise CryptoError("decryption failed (key mismatch or tampered ciphertext)") from e


def encrypt_with_ttl(plaintext: str) -> str:
    """Same as encrypt, but the result carries a Fernet timestamp the caller can verify."""
    return encrypt(plaintext)


def decrypt_with_ttl(ciphertext: str, max_age_seconds: int) -> str:
    """Decrypt and reject if the ciphertext is older than `max_age_seconds`. Used for OAuth state."""
    try:
        return _fernet().decrypt(ciphertext.encode(), ttl=max_age_seconds).decode()
    except InvalidToken as e:
        raise CryptoError("state expired or invalid") from e
