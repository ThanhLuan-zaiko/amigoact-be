"""Delivery of account emails."""

import logging
import smtplib
from email.message import EmailMessage
from typing import Annotated, Protocol

from fastapi import Depends

from src.config import AuthSettings, get_auth_settings

logger = logging.getLogger("src.auth.mailer")


class Mailer(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


class LogMailer:
    """Development fallback. The body holds secret links, so never use it in production."""

    def send(self, to: str, subject: str, body: str) -> None:
        logger.warning("SMTP_HOST is not set. Email to %s: %s\n%s", to, subject, body)


class SmtpMailer:
    def __init__(self, settings: AuthSettings) -> None:
        self._settings = settings

    def send(self, to: str, subject: str, body: str) -> None:
        settings = self._settings
        message = EmailMessage()
        message["From"] = settings.smtp_from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as client:
                client.starttls()
                if settings.smtp_username:
                    client.login(settings.smtp_username, settings.smtp_password)
                client.send_message(message)
        except OSError, smtplib.SMTPException:
            # Runs after the response is sent, so the failure can only be logged.
            logger.exception("Could not send the email: %s", subject)


def get_mailer(
    settings: Annotated[AuthSettings, Depends(get_auth_settings)],
) -> Mailer:
    return SmtpMailer(settings) if settings.smtp_host else LogMailer()
