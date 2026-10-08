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
    Boolean, DateTime, Enum, Float, ForeignKey, ForeignKeyConstraint, Index,
    Integer, String, UniqueConstraint,
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


# ---------------------------------------------------------------------------
# Assessment domain
#
# Everything below is organisation-scoped. A candidate belongs to exactly
# one organisation, and every attempt and score carries the organisation
# forward so that no query can reach across the tenancy boundary even by
# accident.
# ---------------------------------------------------------------------------


class AttemptMode(str, enum.Enum):
    PRACTICE = "practice"
    FORMAL = "formal"


class Candidate(Base):
    """A learner invited by an organisation.

    Candidates are not users. They hold no password and cannot sign in;
    they reach their assessment through a single long-lived access token
    issued at invitation. Learners should not have to manage a credential
    to answer twenty-four questions, and not storing one removes a whole
    category of risk from the largest population in the system.
    """

    __tablename__ = "candidates"
    __table_args__ = (
        UniqueConstraint("organisation_id", "email", name="uq_candidate_org_email"),
        # Target for the composite foreign keys on child tables. Those
        # children denormalise organisation_id so row-level security can
        # be a simple predicate on an indexed column of the same row;
        # the composite key is what stops that copy from ever drifting.
        UniqueConstraint("id", "organisation_id", name="uq_candidate_id_org"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organisation_id: Mapped[int] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200))
    access_token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    invited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    organisation: Mapped[Organisation] = relationship()
    assignments: Mapped[list["CandidateAssignment"]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan"
    )
    attempts: Mapped[list["AssessmentAttempt"]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan",
        order_by="AssessmentAttempt.created_at",
    )


class CandidateAssignment(Base):
    """Which capability constructs a candidate is assessed on.

    No rows means every construct, matching the pre-assignment default.
    An empty assignment set and "not yet customised" are therefore the
    same state, which is the behaviour institutions expect.
    """

    __tablename__ = "candidate_assignments"
    __table_args__ = (
        UniqueConstraint("candidate_id", "construct_id", name="uq_assignment_candidate_construct"),
        ForeignKeyConstraint(
            ["candidate_id", "organisation_id"],
            ["candidates.id", "candidates.organisation_id"],
            ondelete="CASCADE", name="fk_assignment_candidate_org",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(nullable=False, index=True)
    # Denormalised from the candidate so the row-level-security policy is
    # a predicate on this row rather than a subquery. The composite
    # foreign key above makes a mismatched value impossible to insert.
    organisation_id: Mapped[int] = mapped_column(nullable=False, index=True)
    construct_id: Mapped[str] = mapped_column(String(64), nullable=False)

    candidate: Mapped[Candidate] = relationship(back_populates="assignments")


class AssessmentAttempt(Base):
    """One completed assessment run.

    engine_config_version and engine_config_digest are the audit record:
    they bind this result to the exact configuration that produced it, so
    it can be reproduced years later even after the engine has moved on.
    A version label alone would not do -- a label can be edited, a digest
    is derived from the bytes.
    """

    __tablename__ = "assessment_attempts"
    __table_args__ = (
        Index("ix_attempt_org_candidate", "organisation_id", "candidate_id"),
        UniqueConstraint("id", "organisation_id", name="uq_attempt_id_org"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organisation_id: Mapped[int] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mode: Mapped[AttemptMode] = mapped_column(
        Enum(AttemptMode, native_enum=False, length=16), nullable=False
    )
    item_set: Mapped[str] = mapped_column(String(32), nullable=False)
    engine_config_version: Mapped[str] = mapped_column(String(32), nullable=False)
    engine_config_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    overall_normalised: Mapped[float] = mapped_column(Float, nullable=False)
    overall_band: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    candidate: Mapped[Candidate] = relationship(back_populates="attempts")
    construct_scores: Mapped[list["AttemptConstructScore"]] = relationship(
        back_populates="attempt", cascade="all, delete-orphan"
    )


class AttemptConstructScore(Base):
    """Per-construct result for one attempt. Only assessed constructs get
    a row -- an unassessed construct is absent, never stored as zero."""

    __tablename__ = "attempt_construct_scores"
    __table_args__ = (
        UniqueConstraint("attempt_id", "construct_id", name="uq_score_attempt_construct"),
        ForeignKeyConstraint(
            ["attempt_id", "organisation_id"],
            ["assessment_attempts.id", "assessment_attempts.organisation_id"],
            ondelete="CASCADE", name="fk_score_attempt_org",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(nullable=False, index=True)
    # Denormalised for the same reason as candidate_assignments above.
    organisation_id: Mapped[int] = mapped_column(nullable=False, index=True)
    construct_id: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    normalised: Mapped[float] = mapped_column(Float, nullable=False)
    band: Mapped[str] = mapped_column(String(32), nullable=False)

    attempt: Mapped[AssessmentAttempt] = relationship(back_populates="construct_scores")


class TrainingReference(Base):
    """One human-entered mapping from a capability construct to a real,
    citable training.gov.au unit of competency.

    Versioned by lineage rather than mutated: an edit inserts a new row
    sharing lineage_id with version incremented, and clears is_current on
    the previous one. A pathway issued two years ago therefore stays
    reproducible against the data that generated it.

    organisation_id is NULL for a global entry maintained centrally, or
    set for an organisation's own entry or its fork of a global one.
    forked_from_lineage_id records which global entry a fork diverged
    from, so the resolver can substitute the local version in place of
    the default without duplicating the whole library.

    Never populated by an automated request to training.gov.au or
    anywhere else. Every row is typed in by a person who read the public
    page, and training_gov_url points back at it for one-click
    re-verification. verified starts false and is only ever set by a
    person confirming the row is still current.
    """

    __tablename__ = "training_references"
    __table_args__ = (
        Index("ix_reference_lookup", "construct_id", "is_current", "organisation_id"),
        Index("ix_reference_lineage", "lineage_id", "version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    lineage_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    forked_from_lineage_id: Mapped[str | None] = mapped_column(String(64))
    organisation_id: Mapped[int | None] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), index=True
    )
    construct_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    unit_code: Mapped[str] = mapped_column(String(32), nullable=False)
    unit_title: Mapped[str] = mapped_column(String(300), nullable=False)
    qualification_title: Mapped[str | None] = mapped_column(String(300))
    career_path: Mapped[str | None] = mapped_column(String(300))
    training_gov_url: Mapped[str] = mapped_column(String(500), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(1000))
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    review_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
