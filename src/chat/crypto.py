"""Encrypting chat text with AES-256-GCM. The key comes from CHAT_ENCRYPTION_KEY in .env."""

import base64
import binascii
import os
import uuid
from functools import lru_cache

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.config import get_chat_settings

PREFIX = "v1gcm:"
NONCE_BYTES = 12


class CipherError(Exception):
    """Stored text that cannot be opened. It was changed, moved to another row, or written by another key."""


@lru_cache
def _cipher(key: str) -> AESGCM:
    return AESGCM(base64.b64decode(key))


def seal(text: str, bound_to: uuid.UUID) -> str:
    """The row's ID is authenticated, so a ciphertext copied to another row will not open."""
    nonce = os.urandom(NONCE_BYTES)
    cipher = _cipher(get_chat_settings().chat_encryption_key)
    sealed = cipher.encrypt(nonce, text.encode("utf-8"), bound_to.bytes)
    return PREFIX + base64.b64encode(nonce + sealed).decode("ascii")


def open_text(token: str, bound_to: uuid.UUID) -> str:
    if not token.startswith(PREFIX):
        raise CipherError("missing version prefix")
    try:
        raw = base64.b64decode(token[len(PREFIX) :], validate=True)
    except binascii.Error as exc:
        raise CipherError("not base64") from exc
    cipher = _cipher(get_chat_settings().chat_encryption_key)
    try:
        plain = cipher.decrypt(raw[:NONCE_BYTES], raw[NONCE_BYTES:], bound_to.bytes)
    except InvalidTag as exc:
        raise CipherError("authentication failed") from exc
    return plain.decode("utf-8")
