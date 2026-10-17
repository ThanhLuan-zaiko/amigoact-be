"""At-rest encryption for chat text: AES-256-GCM on every stored body.

Scope: this protects the database and backups, not the server itself -
it is not end-to-end encryption. Plaintext rows written before the flag
existed keep decrypting (only the "v1gcm:" prefix is treated as
ciphertext). Attachment metadata and mention names stay plaintext so
previews and notification fan-out keep working.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PREFIX = "v1gcm:"


class ChatCipher:
    """Symmetric body cipher; decrypt() is a no-op on legacy plaintext."""

    def __init__(self, key: bytes) -> None:
        self._aead = AESGCM(key)

    def encrypt(self, text: str) -> str:
        if not text:
            return text
        nonce = os.urandom(12)
        payload = nonce + self._aead.encrypt(nonce, text.encode(), None)
        return PREFIX + base64.urlsafe_b64encode(payload).decode()

    def decrypt(self, text: str | None) -> str:
        if not text:
            return ""
        if not text.startswith(PREFIX):
            return text
        try:
            raw = base64.urlsafe_b64decode(text[len(PREFIX):])
            return self._aead.decrypt(raw[:12], raw[12:], None).decode()
        except Exception:
            # Corrupt ciphertext reads as empty rather than leaking bytes.
            return ""


def chat_cipher(settings) -> ChatCipher:  # noqa: ANN001, ANN201
    """Build the cipher: CHAT_MESSAGE_KEY (base64) or the JWT fallback."""
    key = getattr(settings, "chat_message_key", "") or ""
    if key.strip():
        material = base64.urlsafe_b64decode(key)
    else:
        material = hashlib.sha256(
            f"amigoact-chat:{settings.jwt_secret}".encode()
        ).digest()
    return ChatCipher(material)
