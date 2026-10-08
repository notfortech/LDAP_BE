"""Domain model for self-serve institutional use.

The central change from the predecessor: an organisation is its own
entity. Previously org_id was the inviting administrator's own user id,
which meant one administrator per institution, no colleague access, no
ownership transfer, and an orphaned organisation when that person left.
Self-serve makes all four unacceptable.
"""

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Role(str, enum.Enum):
    """Membership roles.

    Deliberately excludes platform-level privilege. Self-serve grants
    OWNER on the organisation a person creates, and nothing wider. The
    super-admin capability that governs the global reference library is
    not a membership role and cannot be reached by signing up — that
    control predates self-serve and survives it intact.
    """

    OWNER = "owner"
    ADMIN = "admin"


class OrgStatus(str, enum.Enum):
    PENDING_VERIFICATION = "pending_verification"
    ACTIVE = "active"
    SUSPENDED = "suspended"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def is_verified(self) -> bool:
        return self.email_verified_at is not None


class Organisation(Base):
    __tablename__ = "organisations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    contact_email: Mapped[str] = mapped_column(String(320), nullable=False)
    rto_code: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[OrgStatus] = mapped_column(
        Enum(OrgStatus, native_enum=False, length=32),
        default=OrgStatus.PENDING_VERIFICATION, nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="organisation", cascade="all, delete-orphan"
    )

    @property
    def can_operate(self) -> bool:
        """Whether this organisation may perform write operations that
        reach outside itself, such as inviting a candidate."""
        return self.status == OrgStatus.ACTIVE


class Membership(Base):
    """Joins a user to an organisation with a role. This is the only
    thing that grants organisation access — never a token claim, which a
    user who can edit their own profile metadata might influence."""

    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "organisation_id", name="uq_membership_user_org"),
        Index("ix_membership_org_role", "organisation_id", "role"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    organisation_id: Mapped[int] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[Role] = mapped_column(
        Enum(Role, native_enum=False, length=16), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="memberships")
    organisation: Mapped[Organisation] = relationship(back_populates="memberships")


class SessionToken(Base):
    """An authenticated session.

    Opaque random tokens, stored as a SHA-256 digest, rather than a
    self-contained signed token. Three reasons: revocation is immediate
    rather than waiting for an expiry to elapse; a database read cannot
    leak a usable credential; and it needs no cryptography beyond the
    standard library, which keeps the appliance profile dependency-free.
    """

    __tablename__ = "session_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship()


class EmailVerification(Base):
    """A single-use, expiring email ownership proof. Stored hashed for
    the same reason as a session token: the database should never hold a
    directly usable credential."""

    __tablename__ = "email_verifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship()


class AuditEvent(Base):
    """Append-only record of privileged actions. Written by the
    application, never updated or deleted by it."""

    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_org_created", "organisation_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organisation_id: Mapped[int | None] = mapped_column(Integer, index=True)
    actor_user_id: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target: Mapped[str | None] = mapped_column(String(200))
    source_ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
