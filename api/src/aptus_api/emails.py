"""Email delivery behind an adapter.

Development logs the message and returns the token so a developer can
complete a flow without a mail server. Production requires a real
adapter; the null adapter refuses rather than silently dropping mail,
because a verification email that vanishes looks identical to one that
was never sent.
"""

import logging

logger = logging.getLogger("aptus.email")


class EmailAdapter:
    def send_verification(self, to: str, token: str) -> None:
        raise NotImplementedError


class LoggingEmailAdapter(EmailAdapter):
    """Development only. Logs the link instead of sending it."""

    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def send_verification(self, to: str, token: str) -> None:
        self.sent.append((to, token))
        logger.info("Verification token for %s: %s", to, token)


class UnconfiguredEmailAdapter(EmailAdapter):
    def send_verification(self, to: str, token: str) -> None:
        raise RuntimeError(
            "No email adapter is configured. Verification cannot be delivered."
        )
