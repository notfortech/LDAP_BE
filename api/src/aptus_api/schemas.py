"""Request and response shapes.

Note what is absent: no endpoint accepts an organisation identifier in a
request body. Organisation identity comes from the authenticated
session and the membership table only.
"""

import re

from pydantic import BaseModel, EmailStr, Field, field_validator

# Domains that exist to be thrown away. A free tier tied to a disposable
# address is not a free tier, it is an unmetered one.
DISPOSABLE_DOMAINS = frozenset({
    "mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com",
    "throwawaymail.com", "yopmail.com", "trashmail.com", "sharklasers.com",
    "getnada.com", "dispostable.com", "maildrop.cc", "fakeinbox.com",
})

MIN_PASSWORD_LENGTH = 12


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=200)
    organisation_name: str = Field(min_length=2, max_length=200)
    rto_code: str | None = Field(default=None, max_length=20)

    @field_validator("email")
    @classmethod
    def reject_disposable(cls, value: str) -> str:
        if value.rsplit("@", 1)[-1].lower() in DISPOSABLE_DOMAINS:
            raise ValueError("Use a permanent email address for your organisation.")
        return value.lower()

    @field_validator("password")
    @classmethod
    def reject_trivial(cls, value: str) -> str:
        """Length is the dominant factor, so the bar is length plus a
        check against the handful of long strings everyone picks."""
        if value.lower() in {"password1234", "administrator", "changeme1234", "aptuspassword"}:
            raise ValueError("Choose a less predictable password.")
        return value

    @field_validator("rto_code")
    @classmethod
    def normalise_rto(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        code = value.strip().upper()
        if not re.fullmatch(r"[0-9A-Z]{3,20}", code):
            raise ValueError("RTO code must be 3-20 letters or digits.")
        return code


class SigninRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=200)


class VerifyRequest(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class SessionResponse(BaseModel):
    token: str
    expires_at: str


class OrganisationSummary(BaseModel):
    id: int
    name: str
    slug: str
    status: str
    rto_code: str | None
    role: str


class MeResponse(BaseModel):
    email: str
    email_verified: bool
    organisations: list[OrganisationSummary]


class AcceptedResponse(BaseModel):
    """Deliberately uninformative. Signup and resend return this whether
    or not the address was already registered, so neither can be used to
    discover who holds an account."""

    status: str = "accepted"
    detail: str
