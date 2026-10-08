"""Outbound email port. SMTP when configured, suppressed otherwise."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

logger = logging.getLogger("amigoact")


class EmailSender(ABC):
    """Port for transactional email (verification codes, reset codes)."""

    @abstractmethod
    def send_code(self, to_email: str, subject: str, code: str) -> bool:
        """Deliver a single-use code. Returns True when handed to a provider."""


class SmtpEmailSender(EmailSender):
    """Blocking SMTP sender constructed from application settings."""

    def __init__(
        self, host: str, port: int, username: str, password: str, sender: str
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._sender = sender

    def send_code(self, to_email: str, subject: str, code: str) -> bool:
        import smtplib
        from email.message import EmailMessage

        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = to_email
        message["Subject"] = subject
        message.set_content(f"Your AmigoACT code is: {code}")
        try:
            with smtplib.SMTP(self._host, self._port, timeout=10) as client:
                client.starttls()
                if self._username:
                    client.login(self._username, self._password)
                client.send_message(message)
            return True
        except OSError as exc:
            logger.warning("Outbound email failed: %s", exc)
            return False


class SuppressedEmailSender(EmailSender):
    """No-provider fallback. Never logs addresses or codes, only counters."""

    def send_code(self, to_email: str, subject: str, code: str) -> bool:
        del to_email, code
        logger.warning("Outbound email suppressed (no SMTP configured): %s", subject)
        return False


def build_sender(
    host: str, port: int, username: str, password: str, sender: str
) -> EmailSender:
    """Select the SMTP sender when a host is configured, else the suppressor."""
    if host:
        return SmtpEmailSender(host, port, username, password, sender)
    return SuppressedEmailSender()
